"""The three optional integrations. Everything that can run without the extra
dependency runs unconditionally; the rest skips."""

import importlib.util
import json

import pytest
import yaml
from conftest import FakeProvider

from prompt_selector.domain import CompiledPrompt, Message, ModelProfile, ModelResult
from prompt_selector.evals import BenchmarkExample
from prompt_selector.integrations import IntegrationError, promptfoo, require
from prompt_selector.integrations.tracing import (
    CallEvent,
    NullTracer,
    TracingProvider,
    build_tracer,
    write_jsonl,
)
from prompt_selector.providers import ProviderError

HAS_DSPY = importlib.util.find_spec("dspy") is not None
HAS_LANGFUSE = importlib.util.find_spec("langfuse") is not None
HAS_OTEL = importlib.util.find_spec("opentelemetry.sdk") is not None


def dataset(schema):
    return [
        BenchmarkExample(
            id=f"ex-{index}",
            input=f"Person{index} visited Place{index}.",
            expected={"people": [f"Person{index}"], "places": [f"Place{index}"]},
            response_schema=schema,
        )
        for index in range(3)
    ]


# --------------------------------------------------------------------------- #
# shared guard
# --------------------------------------------------------------------------- #


def test_missing_dependency_names_the_extra_to_install():
    with pytest.raises(IntegrationError, match=r"pip install 'prompt-selector\[nope\]'"):
        require("definitely_not_installed_xyz", "nope")


# --------------------------------------------------------------------------- #
# promptfoo export — no third-party dependency needed
# --------------------------------------------------------------------------- #


def test_export_writes_a_runnable_project(tmp_path, extraction_task, entity_schema, registry):
    result = promptfoo.export(
        directory=tmp_path / "pf",
        task=extraction_task,
        techniques=[
            registry.technique("structured.schema-first"),
            registry.technique("direct.explicit-constraints"),
        ],
        dataset=dataset(entity_schema),
        models=[extraction_task.model],
        dataset_name="unit",
    )
    assert result.config_path.exists()
    assert len(result.prompt_paths) == 2
    assert result.bridge_path and result.bridge_path.exists()

    config = yaml.safe_load(result.config_path.read_text())
    assert len(config["tests"]) == 3
    assert {item["label"] for item in config["prompts"]} == {
        "structured.schema-first",
        "direct.explicit-constraints",
    }


def test_exported_prompt_templates_the_input_and_nothing_else(
    tmp_path, extraction_task, entity_schema, registry
):
    result = promptfoo.export(
        directory=tmp_path / "pf",
        task=extraction_task,
        techniques=[registry.technique("structured.schema-first")],
        dataset=dataset(entity_schema),
        models=[extraction_task.model],
    )
    messages = json.loads(result.prompt_paths[0].read_text())
    user = messages[-1]["content"]
    assert "{{input}}" in user
    assert promptfoo.INPUT_SENTINEL not in user
    # The rest of the compiled prompt survives verbatim.
    assert "PROCEDURE" in user
    assert "FIELDS" in user


def test_native_schema_is_enforced_by_the_exported_provider_config(
    extraction_task, entity_schema, registry
):
    """Otherwise promptfoo would measure an unconstrained model and disagree with us."""
    config, _, _ = promptfoo.build_config(
        task=extraction_task,
        techniques=[registry.technique("structured.schema-first")],
        dataset=dataset(entity_schema),
        models=[extraction_task.model],
        dataset_name="unit",
    )
    assert config["providers"][0]["config"]["format"] == entity_schema

    openai_model = ModelProfile(
        provider="openai", model_id="gpt-x", base_url="https://example.invalid"
    )
    config, _, _ = promptfoo.build_config(
        task=extraction_task,
        techniques=[registry.technique("structured.schema-first")],
        dataset=dataset(entity_schema),
        models=[openai_model],
        dataset_name="unit",
    )
    fmt = config["providers"][0]["config"]["response_format"]
    assert fmt["json_schema"]["schema"] == entity_schema


def test_multi_call_techniques_are_flagged_not_silently_truncated(
    extraction_task, entity_schema, registry
):
    _, _, warnings = promptfoo.build_config(
        task=extraction_task,
        techniques=[registry.technique("structured.few-shot-repair")],
        dataset=dataset(entity_schema),
        models=[extraction_task.model],
        dataset_name="unit",
    )
    assert any("only its first stage" in item for item in warnings)


def test_assert_bridge_reproduces_our_grader_scores(
    tmp_path, extraction_task, entity_schema, registry
):
    result = promptfoo.export(
        directory=tmp_path / "pf",
        task=extraction_task,
        techniques=[registry.technique("structured.schema-first")],
        dataset=dataset(entity_schema),
        models=[extraction_task.model],
    )
    namespace: dict = {}
    exec(result.bridge_path.read_text(), namespace)  # noqa: S102 - it is our own generated file
    get_assert = namespace["get_assert"]

    context = {
        "vars": {
            "graders": ["field_f1", "json_validity"],
            "expected": {"people": ["Person0"], "places": ["Place0"]},
        }
    }
    perfect = get_assert('{"people":["Person0"],"places":["Place0"]}', context)
    partial = get_assert('{"people":["Person0"],"places":[]}', context)
    prose = get_assert('Here you go: {"people":[]}', context)

    assert perfect["pass"] is True and perfect["score"] == 1.0
    assert partial["pass"] is False and 0 < partial["score"] < 1
    assert prose["score"] == 0.0


def test_export_rejects_an_empty_dataset(extraction_task, registry):
    with pytest.raises(ValueError):
        promptfoo.build_config(
            task=extraction_task,
            techniques=[registry.technique("structured.schema-first")],
            dataset=[],
            models=[extraction_task.model],
            dataset_name="unit",
        )


# --------------------------------------------------------------------------- #
# tracing
# --------------------------------------------------------------------------- #


class Recorder:
    def __init__(self) -> None:
        self.events: list[CallEvent] = []

    def record(self, event: CallEvent) -> None:
        self.events.append(event)

    def flush(self) -> None:
        return None


@pytest.mark.asyncio
async def test_tracing_provider_records_one_event_per_call(extraction_task):
    recorder = Recorder()
    provider = TracingProvider(FakeProvider(), recorder, metadata={"phase": "unit"})
    prompt = CompiledPrompt(
        technique_id="t", stage="draft", messages=[Message(role="user", content="hi")]
    )
    await provider.generate(prompt, extraction_task.model)

    assert len(recorder.events) == 1
    event = recorder.events[0]
    assert event.prompt.stage == "draft"
    assert (event.prompt_tokens, event.completion_tokens) == (100, 20)
    assert event.metadata["phase"] == "unit"
    assert event.error is None


@pytest.mark.asyncio
async def test_failures_are_traced_and_still_raised(extraction_task):
    class Broken:
        async def generate(self, prompt, model, timeout_seconds=120) -> ModelResult:
            raise ProviderError("connection refused")

    recorder = Recorder()
    provider = TracingProvider(Broken(), recorder)
    prompt = CompiledPrompt(technique_id="t", messages=[Message(role="user", content="hi")])

    with pytest.raises(ProviderError):
        await provider.generate(prompt, extraction_task.model)
    assert recorder.events[0].error and "connection refused" in recorder.events[0].error


@pytest.mark.asyncio
async def test_multi_stage_runs_trace_every_stage(extraction_task, entity_schema, registry):
    from prompt_selector.evals import BenchmarkRunner

    recorder = Recorder()
    provider = TracingProvider(FakeProvider(responses=['{"people": [], "places": []}']), recorder)
    await BenchmarkRunner(provider).run(
        dataset=dataset(entity_schema),
        task=extraction_task,
        technique=registry.technique("structured.few-shot-repair"),
        dataset_name="unit",
    )
    assert len(recorder.events) == 6  # 3 examples x 2 stages
    assert {event.prompt.stage for event in recorder.events} == {"draft", "repair"}


def test_tracing_is_off_unless_asked_for(monkeypatch):
    monkeypatch.delenv("PROMPT_SELECTOR_TRACING", raising=False)
    from prompt_selector.integrations.tracing import tracer_from_env

    assert isinstance(tracer_from_env(), NullTracer)
    assert isinstance(build_tracer("none"), NullTracer)
    with pytest.raises(ValueError, match="Unknown tracing backend"):
        build_tracer("telepathy")


def test_service_leaves_the_provider_alone_when_tracing_is_off(registry, extraction_task):
    from prompt_selector.service import PromptSelectorService

    service = PromptSelectorService(registry, tracer=NullTracer())
    assert not isinstance(service.provider(extraction_task), TracingProvider)

    traced = PromptSelectorService(registry, tracer=Recorder())
    assert isinstance(traced.provider(extraction_task), TracingProvider)


def test_write_jsonl_round_trips(tmp_path):
    from prompt_selector.evals import load_jsonl

    path = tmp_path / "imported.jsonl"
    count = write_jsonl(
        path, [{"id": "a", "input": "hello", "expected": None, "tags": ["imported"]}]
    )
    assert count == 1
    examples = load_jsonl(path)
    assert examples[0].id == "a"
    assert examples[0].expected is None


@pytest.mark.skipif(not HAS_OTEL, reason="opentelemetry not installed")
def test_otlp_tracer_builds_spans_without_a_collector(extraction_task):
    tracer = build_tracer("phoenix", endpoint="http://127.0.0.1:65535/v1/traces", timeout=1)
    prompt = CompiledPrompt(
        technique_id="t", stage="main", messages=[Message(role="user", content="hi")]
    )
    # Export failures must not propagate into the caller's run.
    tracer.record(
        CallEvent(
            prompt=prompt,
            model=extraction_task.model,
            result=ModelResult(content="ok"),
            latency_seconds=0.1,
            prompt_tokens=10,
            completion_tokens=2,
        )
    )
    tracer.provider.shutdown()


# --------------------------------------------------------------------------- #
# DSPy backend
# --------------------------------------------------------------------------- #


def test_litellm_model_mapping():
    from prompt_selector.integrations.dspy_backend import litellm_model

    name, kwargs = litellm_model(ModelProfile(provider="ollama", model_id="llama3.2:3b"))
    assert name == "ollama_chat/llama3.2:3b"
    assert kwargs["api_base"].endswith("11434")

    name, kwargs = litellm_model(
        ModelProfile(provider="openai", model_id="gpt-x", base_url="https://example.invalid")
    )
    assert name == "openai/gpt-x"
    assert kwargs["api_base"] == "https://example.invalid"


def test_dspy_metric_reuses_our_graders(extraction_task, entity_schema, registry):
    from prompt_selector.integrations.dspy_backend import example_score

    example = dataset(entity_schema)[0]
    technique = registry.technique("structured.schema-first")
    perfect, _ = example_score(
        example, '{"people":["Person0"],"places":["Place0"]}', None, technique, extraction_task
    )
    empty, _ = example_score(example, '{"people":[],"places":[]}', None, technique, extraction_task)
    prose, _ = example_score(example, "no json here", None, technique, extraction_task)
    assert perfect > empty > prose


def test_dspy_metric_rewards_fewer_tokens(extraction_task, entity_schema, registry):
    from prompt_selector.integrations.dspy_backend import example_score

    example = dataset(entity_schema)[0]
    technique = registry.technique("structured.schema-first")
    answer = '{"people":["Person0"],"places":["Place0"]}'
    cheap, _ = example_score(
        example, answer, None, technique, extraction_task, token_reference=100, tokens=100
    )
    pricey, _ = example_score(
        example, answer, None, technique, extraction_task, token_reference=100, tokens=400
    )
    assert cheap > pricey


def test_mutable_block_is_never_the_output_contract(registry):
    from prompt_selector.integrations.dspy_backend import mutable_block

    for technique in registry.techniques.values():
        name = mutable_block(technique)
        if name is not None:
            assert name not in {"input", "contract_native", "contract_embedded", "fields"}


@pytest.mark.skipif(not HAS_DSPY, reason="dspy not installed")
@pytest.mark.asyncio
async def test_bootstrap_backend_runs_through_our_pipeline(
    extraction_task, entity_schema, registry
):
    """BootstrapFewShot needs no proposer LM, so it runs fully offline."""
    from prompt_selector.integrations.dspy_backend import optimize_with_dspy

    provider = FakeProvider(responses=['{"people": ["Person0"], "places": ["Place0"]}'])
    result = await optimize_with_dspy(
        task=extraction_task,
        technique=registry.technique("structured.schema-first"),
        dataset=dataset(entity_schema),
        provider=provider,
        optimizer="bootstrap",
        dataset_name="unit",
    )
    assert result.backend == "dspy:bootstrap"
    assert result.total_calls > 0
    assert result.train_size + result.validation_size == 3
    assert result.compiled_prompt["stages"]
    # schema-first has no example block, so bootstrapped demos must be flagged.
    if result.winner.overlay.exemplars:
        assert any("never reach the model" in note for note in result.notes)


@pytest.mark.skipif(not HAS_DSPY, reason="dspy not installed")
@pytest.mark.asyncio
async def test_unknown_dspy_optimizer_is_rejected(extraction_task, entity_schema, registry):
    from prompt_selector.integrations.dspy_backend import optimize_with_dspy

    with pytest.raises(ValueError, match="Unknown DSPy optimizer"):
        await optimize_with_dspy(
            task=extraction_task,
            technique=registry.technique("structured.schema-first"),
            dataset=dataset(entity_schema),
            provider=FakeProvider(),
            optimizer="telepathy",
        )


# --------------------------------------------------------------------------- #
# Hugging Face import — the conversion itself needs no dependency
# --------------------------------------------------------------------------- #

HAS_DATASETS = importlib.util.find_spec("datasets") is not None


def test_detokenize_attaches_punctuation_and_reports_offsets():
    from prompt_selector.integrations.huggingface import detokenize

    text, spans = detokenize(["Mara", "left", "Veyr", "."])
    assert text == "Mara left Veyr."
    assert text[spans[0][0] : spans[0][1]] == "Mara"
    assert text[spans[2][0] : spans[2][1]] == "Veyr"


def test_bio_spans_split_adjacent_entities():
    from prompt_selector.integrations.huggingface import decode_spans

    tags = ["B-Person", "I-Person", "B-Person", "O", "B-Facility"]
    assert decode_spans(tags) == [("Person", 0, 1), ("Person", 2, 2), ("Facility", 4, 4)]


def test_bare_labels_without_bio_merge_a_run():
    """Few-NERD's coarse tags carry no prefix, so a run is one entity."""
    from prompt_selector.integrations.huggingface import decode_spans

    assert decode_spans(["person", "person", "O", "location"]) == [
        ("person", 0, 1),
        ("location", 3, 3),
    ]


def test_converted_gold_is_verbatim_in_the_input():
    """The invariant the whole benchmark rests on."""
    from prompt_selector.integrations.huggingface import MULTICONER_EN, to_example

    example = to_example(
        ["Captain", "Orin", "sailed", "past", "Veyr", ",", "then", "home", "."],
        ["B-OtherPER", "I-OtherPER", "O", "O", "B-HumanSettlement", "O", "O", "O", "O"],
        MULTICONER_EN,
        "unit-1",
    )
    assert example is not None
    assert example["input"] == "Captain Orin sailed past Veyr, then home."
    assert example["expected"] == {"people": ["Captain Orin"], "places": ["Veyr"]}
    for values in example["expected"].values():
        for value in values:
            assert value in example["input"]


def test_unmapped_types_become_empty_not_wrong():
    from prompt_selector.integrations.huggingface import MULTICONER_EN, to_example

    example = to_example(
        ["Dial", "M", "for", "Murder", "was", "screened", "."],
        ["B-VisualWork", "I-VisualWork", "I-VisualWork", "I-VisualWork", "O", "O", "O"],
        MULTICONER_EN,
        "unit-2",
    )
    assert example is not None
    assert example["expected"] == {"people": [], "places": []}


def test_conversion_rejects_misaligned_rows():
    from prompt_selector.integrations.huggingface import MULTICONER_EN, to_example

    assert to_example(["a", "b"], ["O"], MULTICONER_EN, "x") is None
    assert to_example([], [], MULTICONER_EN, "x") is None


def test_sampling_keeps_a_slice_of_empty_examples():
    """Dropping every empty example would reward a prompt that guesses."""
    from prompt_selector.integrations.huggingface import select

    filled = [{"id": f"f{i}", "expected": {"people": ["x"]}} for i in range(50)]
    empty = [{"id": f"e{i}", "expected": {"people": []}} for i in range(50)]
    chosen = select(filled + empty, limit=20, empty_ratio=0.25)

    assert len(chosen) == 20
    blanks = sum(1 for item in chosen if not any(item["expected"].values()))
    assert blanks == 5
    # Deterministic: the same seed yields the same sample.
    assert [item["id"] for item in select(filled + empty, 20, 0.25)] == [
        item["id"] for item in chosen
    ]


def test_schema_matches_the_mapped_fields():
    from prompt_selector.integrations.huggingface import FEW_NERD, build_schema

    schema = build_schema(FEW_NERD.fields)
    assert schema["required"] == ["people", "places", "organizations"]
    assert schema["additionalProperties"] is False


def test_every_preset_declares_its_licence():
    from prompt_selector.integrations.huggingface import PRESETS

    for name, preset in PRESETS.items():
        assert preset.licence, name
        assert preset.citation, name
        assert preset.fields


def test_mbpp_keeps_only_references_supported_by_the_pure_module_whitelist():
    from prompt_selector.integrations.huggingface import MBPP, code_example

    base = {
        "prompt": "Return the integer square root.",
        "test_list": ["assert root(81) == 9"],
        "test_imports": ["import math"],
        "code": "import math\ndef root(x):\n    return math.floor(math.sqrt(x))",
    }
    example = code_example(base, MBPP, "mbpp-safe")
    assert example is not None
    assert example["grader_options"]["test_setup"] == "import math"

    unsafe = dict(base, code="import os\ndef root(x):\n    return x")
    assert code_example(unsafe, MBPP, "mbpp-unsafe") is None

    unsupported = dict(base, code="def root(x):\n    return bin(x)", test_imports=[])
    assert code_example(unsupported, MBPP, "mbpp-unsupported") is None
