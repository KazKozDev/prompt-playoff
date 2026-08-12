from __future__ import annotations

import json

import pytest

from prompt_playoff.compiler import PromptCompiler
from prompt_playoff.domain import (
    Capability,
    CompiledPrompt,
    ModelProfile,
    ModelResult,
    TaskShape,
    TaskType,
)
from prompt_playoff.engine import (
    AuthoredPrompt,
    EngineCache,
    PromptAuthoringError,
    TaskEngine,
    _authored_json,
    engine_profile_from_env,
    resolve_engine_profile,
)
from prompt_playoff.normalizer import normalize_description
from prompt_playoff.providers import ProviderError
from prompt_playoff.registry import Registry

TARGET = ModelProfile(
    provider="ollama",
    model_id="llama3.2:3b",
    capabilities={Capability.structured_output, Capability.system_messages},
)
ENGINE = ModelProfile(provider="openai", model_id="big-model", local=False, base_url="https://x/v1")

PARSE = {
    "task_type": "translation",
    "domain": "legal",
    "complexity": "high",
    "strict_json": False,
    "tools_allowed": False,
    "requires_validation": True,
    "quality": 0.5,
    "reliability": 0.3,
    "latency": 0.1,
    "token_cost": 0.1,
    "reasoning": "The description asks for a rendering into another language.",
}


class RecordingProvider:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[CompiledPrompt] = []

    async def generate(self, prompt, model, timeout_seconds: float = 120) -> ModelResult:
        self.calls.append(prompt)
        return ModelResult(content=self.content)


class SequenceProvider:
    def __init__(self, contents: list[str]) -> None:
        self.contents = iter(contents)
        self.calls: list[CompiledPrompt] = []

    async def generate(self, prompt, model, timeout_seconds: float = 120) -> ModelResult:
        self.calls.append(prompt)
        return ModelResult(content=next(self.contents))


class BrokenProvider:
    async def generate(self, prompt, model, timeout_seconds: float = 120) -> ModelResult:
        raise ProviderError("connection refused")


@pytest.fixture
def cache(tmp_path) -> EngineCache:
    return EngineCache(tmp_path / "engine-cache.json")


@pytest.mark.asyncio
async def test_no_engine_falls_back_to_keyword_matching(cache) -> None:
    engine = TaskEngine(None, cache=cache)
    result = await engine.normalize("Extract entities into strict JSON.", TARGET)
    assert result.source == "keywords"
    assert result.profile.task_type is TaskType.structured_extraction
    assert result.notes == []


@pytest.mark.asyncio
async def test_engine_reads_what_keywords_would_miss(cache) -> None:
    provider = RecordingProvider(json.dumps(PARSE))
    engine = TaskEngine(ENGINE, provider=provider, cache=cache)
    # No keyword in this sentence matches "translation", so the matcher would
    # fall through to its summarization default.
    result = await engine.normalize("Render the contract into German.", TARGET)

    assert result.source == "engine"
    assert result.profile.task_type is TaskType.translation
    assert result.profile.domain == "legal"
    assert result.profile.priorities.quality == pytest.approx(0.5)
    assert result.engine_model_id == "big-model"
    assert any("would have chosen summarization" in note for note in result.notes)


@pytest.mark.asyncio
async def test_engine_answer_is_cached_so_the_parse_stays_reproducible(cache) -> None:
    provider = RecordingProvider(json.dumps(PARSE))
    engine = TaskEngine(ENGINE, provider=provider, cache=cache)
    first = await engine.normalize("Render the contract into German.", TARGET)
    second = await engine.normalize("Render the contract into German.", TARGET)

    assert len(provider.calls) == 1
    assert second.source == "engine-cache"
    assert second.profile.task_type == first.profile.task_type


@pytest.mark.asyncio
async def test_unreachable_engine_falls_back_and_says_so(cache) -> None:
    engine = TaskEngine(ENGINE, provider=BrokenProvider(), cache=cache)
    result = await engine.normalize("Extract entities into strict JSON.", TARGET)

    assert result.source == "keywords"
    assert result.profile.task_type is TaskType.structured_extraction
    assert any("unreachable" in note for note in result.notes)


@pytest.mark.asyncio
async def test_unparseable_answer_falls_back_and_says_so(cache) -> None:
    engine = TaskEngine(ENGINE, provider=RecordingProvider("no json here"), cache=cache)
    result = await engine.normalize("Extract entities into strict JSON.", TARGET)

    assert result.source == "keywords"
    assert any("does not fit the task schema" in note for note in result.notes)


@pytest.mark.asyncio
async def test_answer_outside_the_task_vocabulary_is_rejected(cache) -> None:
    payload = {**PARSE, "task_type": "poetry"}
    engine = TaskEngine(ENGINE, provider=RecordingProvider(json.dumps(payload)), cache=cache)
    result = await engine.normalize("Extract entities into strict JSON.", TARGET)
    assert result.source == "keywords"


@pytest.mark.asyncio
async def test_overrides_win_over_the_engine(cache) -> None:
    engine = TaskEngine(ENGINE, provider=RecordingProvider(json.dumps(PARSE)), cache=cache)
    result = await engine.normalize(
        "Render the contract into German.",
        TARGET,
        overrides={"task_type": "coding"},
    )
    assert result.profile.task_type is TaskType.coding


@pytest.mark.asyncio
async def test_engine_call_is_deterministic_and_schema_bound(cache) -> None:
    provider = RecordingProvider(json.dumps(PARSE))
    engine = TaskEngine(ENGINE, provider=provider, cache=cache)
    await engine.normalize("Render the contract into German.", TARGET)

    prompt = provider.calls[0]
    assert prompt.generation_options["temperature"] == 0.0
    assert prompt.response_schema is not None
    assert prompt.response_schema["properties"]["task_type"]["enum"] == [
        item.value for item in TaskType
    ]


def test_env_configures_the_engine(monkeypatch) -> None:
    monkeypatch.delenv("PROMPT_PLAYOFF_ENGINE_MODEL", raising=False)
    assert engine_profile_from_env() is None

    monkeypatch.setenv("PROMPT_PLAYOFF_ENGINE_MODEL", "qwen3:14b")
    profile = engine_profile_from_env()
    assert profile is not None
    assert profile.model_id == "qwen3:14b"
    assert profile.provider == "ollama"


def test_explicit_profile_beats_the_environment(monkeypatch) -> None:
    monkeypatch.setenv("PROMPT_PLAYOFF_ENGINE_MODEL", "from-env")
    resolved = resolve_engine_profile(ENGINE)
    assert resolved is not None
    assert resolved.model_id == "big-model"


def coding_scaffold():
    task = normalize_description("Write a Snake game in Python.", TARGET)
    technique = Registry.load().technique("reasoning.chain-of-draft")
    scaffold = PromptCompiler().compile(task, technique, "Write a Snake game in Python.")
    return technique, scaffold


def authored_payload(scaffold, *, include_placeholders: bool = True) -> dict:
    stages = []
    for stage in scaffold.stages:
        slots = " ".join(f"{{{name}}}" for name in stage.deferred_placeholders)
        if not include_placeholders:
            slots = ""
        stages.append(
            {
                "stage": stage.stage,
                "system": "You are a senior Python game developer.",
                "user": (
                    "Create a complete playable Snake game in Python. Define controls, "
                    f"collision rules, scoring, files, and run instructions. {slots}"
                ).strip(),
            }
        )
    return {"stages": stages}


@pytest.mark.asyncio
async def test_engine_authors_real_task_specific_messages_and_preserves_contract(cache) -> None:
    technique, scaffold = coding_scaffold()
    provider = RecordingProvider(json.dumps(authored_payload(scaffold)))
    engine = TaskEngine(ENGINE, provider=provider, cache=cache)

    program = await engine.author(
        "Write a Snake game in Python.", technique, scaffold, reusable=False
    )

    assert program.artifact_source == "engine"
    assert program.authored_by_model == "big-model"
    assert "senior Python game developer" in program.stages[0].messages[0].content
    assert "SELECTED METHOD: Chain of draft" in program.stages[0].messages[0].content
    assert "METHOD RULES" in program.stages[0].messages[0].content
    assert program.strategy == scaffold.strategy
    assert program.validators == scaffold.validators
    assert provider.calls[0].response_schema is not None
    assert provider.calls[0].generation_options["temperature"] == 0.0
    request = provider.calls[0].messages[1].content
    assert "FULL TECHNIQUE RECIPE" in request
    assert "DETERMINISTIC EXECUTION SCAFFOLD" in request
    assert "Write a Snake game in Python." in request
    assert "Write a Snake game in Python." in program.stages[0].messages[1].content


@pytest.mark.asyncio
async def test_engine_authoring_accepts_fenced_top_level_stage_array(cache) -> None:
    technique, scaffold = coding_scaffold()
    content = "```json\n" + json.dumps(authored_payload(scaffold)["stages"]) + "\n```"
    engine = TaskEngine(ENGINE, provider=RecordingProvider(content), cache=cache)
    program = await engine.author("Write a Snake game in Python.", technique, scaffold)
    assert program.artifact_source == "engine"


@pytest.mark.asyncio
async def test_engine_retries_when_first_authoring_attempt_only_copies_scaffold(cache) -> None:
    technique, scaffold = coding_scaffold()
    unchanged = {
        "stages": [
            {
                "stage": stage.stage,
                "system": next(
                    message.content for message in stage.messages if message.role == "system"
                ),
                "user": next(
                    message.content for message in stage.messages if message.role == "user"
                ),
            }
            for stage in scaffold.stages
        ]
    }
    provider = SequenceProvider([json.dumps(unchanged), json.dumps(authored_payload(scaffold))])
    engine = TaskEngine(ENGINE, provider=provider, cache=cache)

    program = await engine.author("Write a Snake game in Python.", technique, scaffold)

    assert program.artifact_source == "engine"
    assert len(provider.calls) == 2
    assert "REPAIR REQUIRED" in provider.calls[1].messages[1].content


@pytest.mark.asyncio
async def test_engine_authored_prompt_is_cached(cache) -> None:
    technique, scaffold = coding_scaffold()
    provider = RecordingProvider(json.dumps(authored_payload(scaffold)))
    engine = TaskEngine(ENGINE, provider=provider, cache=cache)
    await engine.author("Write a Snake game in Python.", technique, scaffold)
    second = await engine.author("Write a Snake game in Python.", technique, scaffold)
    assert len(provider.calls) == 1
    assert "(cached)" in second.notes[0]


@pytest.mark.asyncio
async def test_method_contract_keeps_single_stage_techniques_visibly_distinct(cache) -> None:
    task = normalize_description("Summarize this report.", TARGET)
    registry = Registry.load()
    compiler = PromptCompiler()
    direct = registry.technique("direct.explicit-constraints")
    schema_first = registry.technique("structured.schema-first")
    direct_scaffold = compiler.compile(task, direct, "Summarize this report.")
    schema_first_scaffold = compiler.compile(task, schema_first, "Summarize this report.")

    # A weak author model may return the same generic wording for both methods.
    generic = {
        "stages": [
            {
                "stage": "main",
                "system": "You are a helpful assistant.",
                "user": "Summarize the report clearly and accurately.",
            }
        ]
    }
    provider = RecordingProvider(json.dumps(generic))
    engine = TaskEngine(ENGINE, provider=provider, cache=cache)

    direct_program = await engine.author("Summarize this report.", direct, direct_scaffold)
    schema_first_program = await engine.author(
        "Summarize this report.", schema_first, schema_first_scaffold
    )

    direct_system = direct_program.main.messages[0].content
    schema_first_system = schema_first_program.main.messages[0].content
    assert direct_system != schema_first_system
    assert direct.id in direct_system
    assert schema_first.id in schema_first_system
    assert direct.recipe.instructions[0] in direct_system
    assert schema_first.recipe.instructions[0] in schema_first_system
    direct_user = direct_program.main.messages[1].content
    schema_first_user = schema_first_program.main.messages[1].content
    assert direct_user != schema_first_user
    assert direct_scaffold.main.messages[1].content in direct_user
    assert schema_first_scaffold.main.messages[1].content in schema_first_user


@pytest.mark.asyncio
async def test_engine_cannot_replace_selected_technique_prompt_blocks(cache) -> None:
    description = "Summarize this report and cite the evidence for every claim."
    task = normalize_description(description, TARGET)
    technique = Registry.load().technique("grounding.evidence-first")
    scaffold = PromptCompiler().compile(task, technique, description)
    generic = {
        "stages": [
            {
                "stage": "main",
                "system": "You are a helpful assistant.",
                "user": "Give a clear and concise answer.",
            }
        ]
    }
    engine = TaskEngine(ENGINE, provider=RecordingProvider(json.dumps(generic)), cache=cache)

    program = await engine.author(description, technique, scaffold)

    user = program.main.messages[1].content
    assert scaffold.main.messages[1].content in user
    assert "EVIDENCE AND QUESTION" in user
    assert "TASK-SPECIFIC GUIDANCE" in user


@pytest.mark.asyncio
async def test_engine_authoring_fails_closed_on_invalid_contract(cache) -> None:
    technique, scaffold = coding_scaffold()
    payload = authored_payload(scaffold, include_placeholders=False)
    engine = TaskEngine(ENGINE, provider=RecordingProvider(json.dumps(payload)), cache=cache)
    with pytest.raises(PromptAuthoringError, match="invalid prompt"):
        await engine.author("Write a Snake game in Python.", technique, scaffold, reusable=True)


@pytest.mark.asyncio
async def test_engine_authoring_repairs_stage_placeholder_as_direct_input(cache) -> None:
    technique, scaffold = coding_scaffold()
    payload = authored_payload(scaffold)
    payload["stages"][0]["user"] += "\nINPUT\n{main}"
    engine = TaskEngine(ENGINE, provider=RecordingProvider(json.dumps(payload)), cache=cache)

    program = await engine.author("Write a Snake game in Python.", technique, scaffold)

    text = program.stages[0].messages[1].content
    assert "{main}" not in text
    assert "Write a Snake game in Python." in text


@pytest.mark.asyncio
async def test_engine_authoring_repairs_input_placeholder_in_direct_mode(cache) -> None:
    technique, scaffold = coding_scaffold()
    payload = authored_payload(scaffold)
    payload["stages"][0]["user"] += "\nTASK\n{input}"
    engine = TaskEngine(ENGINE, provider=RecordingProvider(json.dumps(payload)), cache=cache)

    program = await engine.author("Write a Snake game in Python.", technique, scaffold)

    text = program.stages[0].messages[1].content
    assert "{input}" not in text
    assert "Write a Snake game in Python." in text


@pytest.mark.asyncio
async def test_engine_authoring_still_rejects_unknown_placeholder(cache) -> None:
    technique, scaffold = coding_scaffold()
    payload = authored_payload(scaffold)
    payload["stages"][0]["user"] += "\nSOURCE\n{evidence_document}"
    engine = TaskEngine(ENGINE, provider=RecordingProvider(json.dumps(payload)), cache=cache)

    with pytest.raises(PromptAuthoringError, match="invalid prompt"):
        await engine.author("Write a Snake game in Python.", technique, scaffold)


@pytest.mark.asyncio
async def test_reusable_authoring_requires_input_placeholder(cache) -> None:
    task = normalize_description("Summarize reports for executives.", TARGET)
    technique = Registry.load().technique("grounding.evidence-first")
    scaffold = PromptCompiler().compile(task, technique, "{input}")
    payload = {
        "stages": [
            {
                "stage": "main",
                "system": "You summarize supplied evidence for executives.",
                "user": "Summarize the supplied evidence and map every claim to it.",
            }
        ]
    }
    engine = TaskEngine(ENGINE, provider=RecordingProvider(json.dumps(payload)), cache=cache)

    with pytest.raises(PromptAuthoringError, match="invalid prompt"):
        await engine.author("Summarize reports for executives.", technique, scaffold, reusable=True)


@pytest.mark.asyncio
async def test_direct_authoring_appends_original_task_when_model_only_paraphrases(cache) -> None:
    task_text = "Design an LLM agent using only the supplied technical evidence."
    task = normalize_description(task_text, TARGET)
    technique = Registry.load().technique("grounding.evidence-first")
    scaffold = PromptCompiler().compile(task, technique, task_text)
    payload = {
        "stages": [
            {
                "stage": "main",
                "system": "You are a technical architect.",
                "user": "Produce an evidence-grounded architecture and cite every claim.",
            }
        ]
    }
    engine = TaskEngine(ENGINE, provider=RecordingProvider(json.dumps(payload)), cache=cache)

    program = await engine.author(task_text, technique, scaffold)

    user_message = program.stages[0].messages[1].content
    assert task_text in user_message
    assert scaffold.main.messages[1].content in user_message
    assert "{main}" not in user_message


@pytest.mark.asyncio
async def test_engine_authoring_never_falls_back_when_provider_is_down(cache) -> None:
    technique, scaffold = coding_scaffold()
    engine = TaskEngine(ENGINE, provider=BrokenProvider(), cache=cache)
    with pytest.raises(PromptAuthoringError, match="unreachable"):
        await engine.author("Write a Snake game in Python.", technique, scaffold)


@pytest.mark.asyncio
async def test_an_engine_that_echoes_the_scaffold_yields_a_labelled_prompt(cache) -> None:
    """A poor answer is not an unusable one, and must not cost the caller the prompt."""
    technique, scaffold = coding_scaffold()
    unchanged = {
        "stages": [
            {
                "stage": stage.stage,
                "system": stage.messages[0].content,
                "user": stage.messages[1].content,
            }
            for stage in scaffold.stages
        ]
    }
    provider = RecordingProvider(json.dumps(unchanged))
    engine = TaskEngine(ENGINE, provider=provider, cache=cache)

    program = await engine.author("Write a Snake game in Python.", technique, scaffold)

    assert len(provider.calls) == 2
    assert program.artifact_source == "deterministic_compiler"
    assert program.authored_by_model is None
    assert "added nothing about this task" in program.notes[0]
    for written, compiled in zip(program.stages, scaffold.stages, strict=True):
        assert written.messages[1].content == compiled.messages[1].content


@pytest.mark.asyncio
async def test_authored_sections_replace_scaffold_bodies_instead_of_repeating_them(cache) -> None:
    description = "собери в интернете статьи про архитектуры агентов ллм за 2026 год"
    task = normalize_description(description, TARGET)
    technique = Registry.load().technique("grounding.evidence-first")
    scaffold = PromptCompiler().compile(task, technique, description)
    authored = {
        "stages": [
            {
                "stage": "main",
                "system": "You are a research analyst for LLM agent architectures.",
                "user": (
                    "OBJECTIVE\nList every 2026 paper on LLM agent architectures.\n\n"
                    "PROCEDURE\n1. Quote the span naming the venue and year.\n\n"
                    f"EVIDENCE AND QUESTION\n{description}"
                ),
            }
        ]
    }
    engine = TaskEngine(ENGINE, provider=RecordingProvider(json.dumps(authored)), cache=cache)

    program = await engine.author(description, technique, scaffold)

    user = program.main.messages[1].content
    assert user.count("EVIDENCE AND QUESTION") == 1
    assert user.count(description) == 1
    assert "List every 2026 paper on LLM agent architectures." in user
    assert "Answer using only the supplied evidence" not in user
    assert "TASK-SPECIFIC GUIDANCE" not in user


@pytest.mark.asyncio
async def test_untitled_authored_text_is_still_appended_as_guidance(cache) -> None:
    description = "Summarize this report and cite the evidence for every claim."
    task = normalize_description(description, TARGET)
    technique = Registry.load().technique("grounding.evidence-first")
    scaffold = PromptCompiler().compile(task, technique, description)
    authored = {
        "stages": [
            {
                "stage": "main",
                "system": "You summarize supplied evidence.",
                "user": "Prefer figures over adjectives when the evidence gives both.",
            }
        ]
    }
    engine = TaskEngine(ENGINE, provider=RecordingProvider(json.dumps(authored)), cache=cache)

    program = await engine.author(description, technique, scaffold)

    user = program.main.messages[1].content
    assert scaffold.main.messages[1].content in user
    assert "TASK-SPECIFIC GUIDANCE" in user
    assert "Prefer figures over adjectives" in user


@pytest.mark.asyncio
async def test_engine_parse_reports_a_task_that_must_gather_its_material(cache) -> None:
    payload = dict(
        PARSE,
        task_type="research",
        tools_allowed=False,
        retrieval_required=True,
        reasoning="The description says to collect the papers from the internet.",
    )
    engine = TaskEngine(ENGINE, provider=RecordingProvider(json.dumps(payload)), cache=cache)

    result = await engine.normalize("собери в интернете статьи за 2026 год", TARGET)

    assert result.profile.constraints.retrieval_required is True
    assert result.profile.constraints.tools_allowed is True


def multistage_scaffold():
    description = "Plan a migration from Postgres 14 to 16 with zero downtime."
    task = normalize_description(description, TARGET)
    technique = Registry.load().technique("reasoning.decomposition")
    scaffold = PromptCompiler().compile(task, technique, description)
    return description, technique, scaffold


def stage_payload(scaffold, *, generic_from: int) -> dict:
    """Task-specific up to `generic_from`, then the scaffold text verbatim."""
    stages = []
    for index, stage in enumerate(scaffold.stages):
        compiled_user = next(
            message.content for message in stage.messages if message.role == "user"
        )
        slots = " ".join(f"{{{name}}}" for name in stage.deferred_placeholders)
        stages.append(
            {
                "stage": stage.stage,
                "system": "You are a database migration planner.",
                "user": compiled_user
                if index >= generic_from
                else (
                    "Produce the cutover plan for the Postgres 14 to 16 migration, with the "
                    f"replication checks and the rollback trigger for each step. {slots}"
                ).strip(),
            }
        )
    return {"stages": stages}


@pytest.mark.asyncio
async def test_a_stage_that_repeats_the_scaffold_is_authored_again(cache) -> None:
    description, technique, scaffold = multistage_scaffold()
    assert len(scaffold.stages) > 1
    provider = SequenceProvider(
        [
            json.dumps(stage_payload(scaffold, generic_from=1)),
            json.dumps(stage_payload(scaffold, generic_from=len(scaffold.stages))),
        ]
    )
    engine = TaskEngine(ENGINE, provider=provider, cache=cache)

    program = await engine.author(description, technique, scaffold)

    assert len(provider.calls) == 2
    assert "stages" in provider.calls[1].messages[1].content
    assert scaffold.stages[1].stage in provider.calls[1].messages[1].content
    last_stage_user = program.stages[-1].messages[1].content
    assert "rollback trigger" in last_stage_user
    assert "{previous}" in last_stage_user


@pytest.mark.asyncio
async def test_a_generic_later_stage_is_kept_when_the_retry_also_repeats_it(cache) -> None:
    description, technique, scaffold = multistage_scaffold()
    payload = json.dumps(stage_payload(scaffold, generic_from=1))
    provider = SequenceProvider([payload, payload])
    engine = TaskEngine(ENGINE, provider=provider, cache=cache)

    program = await engine.author(description, technique, scaffold)

    assert len(provider.calls) == 2
    assert "{previous}" in program.stages[-1].messages[1].content
    assert "cutover plan" in program.stages[0].messages[1].content


@pytest.mark.asyncio
async def test_guidance_drops_what_the_scaffold_already_says(cache) -> None:
    description, technique, scaffold = multistage_scaffold()
    compiled_user = next(
        message.content for message in scaffold.stages[-1].messages if message.role == "user"
    )
    echo = compiled_user.split("\n\n")[0]
    authored = {
        "stages": [
            {
                "stage": stage.stage,
                "system": "You are a database migration planner.",
                "user": (
                    f"{echo}\n\nRun the cutover rehearsal on a replica first. "
                    + " ".join(f"{{{name}}}" for name in stage.deferred_placeholders)
                ).strip(),
            }
            for stage in scaffold.stages
        ]
    }
    engine = TaskEngine(ENGINE, provider=RecordingProvider(json.dumps(authored)), cache=cache)

    program = await engine.author(description, technique, scaffold)

    user = program.stages[-1].messages[1].content
    assert user.count(echo) == 1
    assert "Run the cutover rehearsal on a replica first." in user
    assert user.count("{previous}") == 1


@pytest.mark.asyncio
async def test_guidance_drops_a_retyped_copy_of_the_task(cache) -> None:
    description, technique, scaffold = multistage_scaffold()
    typo = description.replace("migration", "migrationn")
    authored = {
        "stages": [
            {
                "stage": stage.stage,
                "system": "You are a database migration planner.",
                "user": (
                    f"{typo}\n\nReport the cutover window in UTC. "
                    + " ".join(f"{{{name}}}" for name in stage.deferred_placeholders)
                ).strip(),
            }
            for stage in scaffold.stages
        ]
    }
    engine = TaskEngine(ENGINE, provider=RecordingProvider(json.dumps(authored)), cache=cache)

    program = await engine.author(description, technique, scaffold)

    user = program.stages[-1].messages[1].content
    assert typo not in user
    assert "Report the cutover window in UTC." in user


def test_author_cache_key_survives_a_restart() -> None:
    """Sets dump in hash order, so the key must not be built from that order."""
    description, technique, scaffold = multistage_scaffold()
    engine = TaskEngine(ENGINE)
    key = engine.author_cache_key(description, technique, scaffold, False)

    shuffled = technique.model_copy(
        update={
            "strong_tasks": set(reversed(list(technique.strong_tasks))),
            "tags": set(reversed(list(technique.tags))),
        }
    )

    assert engine.author_cache_key(description, shuffled, scaffold, False) == key


@pytest.mark.asyncio
async def test_engine_reads_the_shape_of_the_request(cache) -> None:
    payload = dict(
        PARSE,
        task_type="coding",
        shape=["multi_step", "high_stakes"],
        reasoning="The description asks for a migration in dependent steps.",
    )
    engine = TaskEngine(ENGINE, provider=RecordingProvider(json.dumps(payload)), cache=cache)

    result = await engine.normalize("Migrate billing to the new ledger, step by step.", TARGET)

    assert result.profile.shape == {TaskShape.multi_step, TaskShape.high_stakes}


@pytest.mark.asyncio
async def test_keyword_shape_stands_in_when_the_engine_names_none(cache) -> None:
    description = "спроектируй сервис очередей: сначала схема, затем API, потом деплой"
    payload = dict(PARSE, task_type="coding", shape=[])
    engine = TaskEngine(ENGINE, provider=RecordingProvider(json.dumps(payload)), cache=cache)

    result = await engine.normalize(description, TARGET)

    assert TaskShape.multi_step in result.profile.shape


STAGE_JSON = '{"stage": "draft", "system": "s", "user": "u"}'


@pytest.mark.parametrize(
    ("label", "answer"),
    [
        ("bare object", f'{{"stages": [{STAGE_JSON}]}}'),
        ("fenced array", f"```json\n[{STAGE_JSON}]\n```"),
        ("fenced array behind a sentence", f"Here it is:\n```json\n[{STAGE_JSON}]\n```"),
        ("array behind a sentence", f"Here it is:\n[{STAGE_JSON}]"),
        ("object after reasoning", f'<think>plan {{a}} [b]</think>\n{{"stages": [{STAGE_JSON}]}}'),
        ("object with a trailing note", f'{{"stages": [{STAGE_JSON}]}}\n\nHope this helps!'),
        (
            "stage names used as keys",
            '```json\n{"draft": {"system": "s", "user": "u"}}\n```',
        ),
        (
            "a stages object instead of a list",
            '{"stages": {"draft": {"system": "s", "user": "u"}}}',
        ),
        (
            "braces inside the prompt text",
            '{"stages": [{"stage": "draft", "system": "s", "user": "emit {\\"a\\": 1}"}]}',
        ),
    ],
)
def test_an_authored_answer_is_read_out_of_whatever_surrounds_it(label, answer) -> None:
    payload = _authored_json(answer)

    assert payload is not None, label
    assert AuthoredPrompt.model_validate(payload).stages[0].stage == "draft", label


def test_stage_objects_in_a_row_are_read_as_stages() -> None:
    second = STAGE_JSON.replace("draft", "answer")
    answer = f"First:\n{STAGE_JSON}\nSecond:\n{second}"

    payload = _authored_json(answer)

    assert [stage.stage for stage in AuthoredPrompt.model_validate(payload).stages] == [
        "draft",
        "answer",
    ]


def test_an_answer_without_json_is_still_no_answer() -> None:
    assert _authored_json("I cannot do that.") is None
    assert _authored_json("") is None


def test_stage_names_as_keys_keep_their_order() -> None:
    answer = (
        '{"draft": {"system": "s", "user": "u"}, '
        '"answer": {"system": "s2", "user": "u2 {previous}"}}'
    )

    payload = _authored_json(answer)

    assert [stage.stage for stage in AuthoredPrompt.model_validate(payload).stages] == [
        "draft",
        "answer",
    ]
