import json
import re

import pytest

from prompt_selector.domain import (
    CompiledPrompt,
    ModelProfile,
    ModelResult,
    TaskProfile,
    TaskType,
)
from prompt_selector.evals import BenchmarkExample, Scorecard
from prompt_selector.optimizer import Candidate, PromptOptimizer, TechniqueOverlay, pareto_front


class ScriptedProvider:
    """A model that only answers correctly once the prompt carries the better rule.

    It reads the example out of the prompt, so every example is graded on its own
    expected answer rather than a single canned response.
    """

    def __init__(self, rewrite: str, marker: str = "SHARPER RULE") -> None:
        self.rewrite = rewrite
        self.marker = marker
        self.rewrites_requested = 0

    async def generate(
        self, prompt: CompiledPrompt, model: ModelProfile, timeout_seconds: float = 120
    ) -> ModelResult:
        if prompt.technique_id == "optimizer.meta":
            self.rewrites_requested += 1
            return ModelResult(
                content=self.rewrite, usage={"prompt_eval_count": 40, "eval_count": 20}
            )
        body = prompt.messages[-1].content
        match = re.search(r"(Person\d+) visited (Place\d+)\.", body)
        if self.marker in body and match:
            content = json.dumps({"people": [match.group(1)], "places": [match.group(2)]})
        else:
            content = '{"people": [], "places": []}'
        return ModelResult(content=content, usage={"prompt_eval_count": 100, "eval_count": 20})


def dataset(schema):
    return [
        BenchmarkExample(
            id=f"ex-{i}",
            input=f"Person{i} visited Place{i}.",
            expected={"people": [f"Person{i}"], "places": [f"Place{i}"]},
            response_schema=schema,
        )
        for i in range(4)
    ]


@pytest.mark.asyncio
async def test_optimizer_finds_and_verifies_a_better_prompt(
    extraction_task, entity_schema, registry
):
    provider = ScriptedProvider(rewrite="SHARPER RULE: copy names verbatim, including titles.")
    optimizer = PromptOptimizer(provider)
    result = await optimizer.optimize(
        task=extraction_task,
        technique=registry.technique("structured.schema-first"),
        dataset=dataset(entity_schema),
        rounds=2,
        candidates_per_round=1,
        dataset_name="unit",
    )

    assert provider.rewrites_requested >= 1
    assert result.winner.origin.startswith("reflection")
    assert result.winner_validation.quality > result.baseline_validation.quality
    assert result.improvement["quality"] > 0
    assert "SHARPER RULE" in result.compiled_prompt["stages"][0]["user"]
    # 3 bootstrap + 3 round-1 + 1 proposal + 3 round-2 + 2 validation calls.
    assert result.total_calls == 12


@pytest.mark.asyncio
async def test_train_and_validation_never_overlap(extraction_task, entity_schema, registry):
    provider = ScriptedProvider(rewrite="same")
    result = await PromptOptimizer(provider).optimize(
        task=extraction_task,
        technique=registry.technique("structured.schema-first"),
        dataset=dataset(entity_schema),
        rounds=1,
        dataset_name="unit",
    )
    assert result.train_size >= 1
    assert result.validation_size >= 1
    assert result.train_size + result.validation_size == 4


@pytest.mark.asyncio
async def test_a_rewrite_identical_to_the_original_is_discarded(
    extraction_task, entity_schema, registry
):
    technique = registry.technique("structured.schema-first")
    unchanged = next(b for b in technique.recipe.blocks if b.name == "procedure").body
    provider = ScriptedProvider(rewrite=unchanged)
    result = await PromptOptimizer(provider).optimize(
        task=extraction_task,
        technique=technique,
        dataset=dataset(entity_schema),
        rounds=2,
        candidates_per_round=2,
        dataset_name="unit",
    )
    assert result.winner.id in {"baseline", "bootstrap-demos"}


def test_overlay_never_mutates_the_registry_technique(registry):
    technique = registry.technique("structured.schema-first")
    original = technique.recipe.system
    patched = TechniqueOverlay(system="replaced").apply(technique)
    assert patched.recipe.system == "replaced"
    assert technique.recipe.system == original


def test_append_overlay_preserves_original_block_text(registry):
    technique = registry.technique("structured.schema-first")
    original = next(block.body for block in technique.recipe.blocks if block.name == "procedure")
    overlay = TechniqueOverlay(
        block_appends={"procedure": "Keep a title attached to the person's name."}
    )

    patched = overlay.apply(technique)
    body = next(block.body for block in patched.recipe.blocks if block.name == "procedure")

    assert body.startswith(original)
    assert body == original + "Keep a title attached to the person's name.\n"
    assert (
        next(block.body for block in technique.recipe.blocks if block.name == "procedure")
        == original
    )


def card(quality, reliability, tokens, latency):
    return Scorecard(
        quality=quality,
        reliability=reliability,
        contract_pass_rate=1.0,
        stability=1.0,
        mean_latency_seconds=latency,
        p95_latency_seconds=latency,
        mean_total_tokens=tokens,
        mean_prompt_tokens=tokens,
        mean_completion_tokens=0,
        mean_calls=1,
        runs=1,
    )


def test_pareto_front_keeps_the_cheap_and_the_accurate():
    accurate = Candidate(
        id="accurate", technique_id="t", origin="x", train=card(0.9, 1.0, 500, 2.0)
    )
    cheap = Candidate(id="cheap", technique_id="t", origin="x", train=card(0.7, 1.0, 100, 0.5))
    dominated = Candidate(id="bad", technique_id="t", origin="x", train=card(0.6, 0.9, 600, 3.0))

    front = {item.id for item in pareto_front([accurate, cheap, dominated])}
    assert front == {"accurate", "cheap"}


def test_a_winner_carrying_unrenderable_demos_is_flagged(registry):
    """bootstrap can "win" with demos a technique has no block to render."""
    from prompt_selector.domain import Exemplar
    from prompt_selector.providers import OllamaProvider

    optimizer = PromptOptimizer(OllamaProvider())
    technique = registry.technique("structured.schema-first")
    winner = Candidate(
        id="bootstrap-demos",
        technique_id=technique.id,
        origin="bootstrap",
        overlay=TechniqueOverlay(exemplars=[Exemplar(input="a", output="b")]),
    )
    notes = optimizer._diagnosis(technique, winner)
    assert any("never reach the model" in note for note in notes)

    # A technique that does render demonstrations must not be flagged.
    with_demos = registry.technique("structured.few-shot-repair")
    assert optimizer._diagnosis(with_demos, winner) == []


def test_discarded_proposals_are_reported_not_swallowed(registry):
    from prompt_selector.providers import OllamaProvider

    optimizer = PromptOptimizer(OllamaProvider())
    optimizer.proposal_failures = ["proposer call failed: timeout"] * 3
    optimizer.proposals_accepted = 0
    notes = optimizer._diagnosis(
        registry.technique("structured.schema-first"),
        Candidate(id="baseline", technique_id="t", origin="baseline"),
    )
    assert any("3 proposal(s) discarded" in note for note in notes)
    assert any("proposer problem, not a result" in note for note in notes)


def scored(name, quality, tokens, weighted):
    item = Candidate(id=name, technique_id="t", origin="x", train=card(quality, 1.0, tokens, 1.0))
    item.score = weighted
    return item


def test_beam_keeps_the_quality_leader_the_weighted_score_would_drop():
    """A verbose but more accurate candidate is the interesting parent."""
    from prompt_selector.optimizer import select_parents

    cheap = scored("cheap", quality=0.60, tokens=100, weighted=0.90)
    accurate = scored("accurate", quality=0.85, tokens=600, weighted=0.70)
    dull = scored("dull", quality=0.55, tokens=300, weighted=0.80)

    ranked = sorted([cheap, accurate, dull], key=lambda item: item.score, reverse=True)
    parents = select_parents(ranked, beam_width=2)

    assert [item.id for item in parents] == ["cheap", "accurate"]
    # A width of one collapses back to the old greedy behaviour.
    assert [item.id for item in select_parents(ranked, beam_width=1)] == ["cheap"]


def test_beam_fills_remaining_slots_by_weighted_score():
    from prompt_selector.optimizer import select_parents

    best = scored("best", quality=0.9, tokens=100, weighted=0.95)
    second = scored("second", quality=0.5, tokens=100, weighted=0.80)
    third = scored("third", quality=0.4, tokens=100, weighted=0.70)
    ranked = [best, second, third]

    # best leads on both axes, so the extra slots go to the next weighted scores.
    assert [item.id for item in select_parents(ranked, beam_width=3)] == [
        "best",
        "second",
        "third",
    ]


def test_select_parents_survives_unevaluated_candidates():
    from prompt_selector.optimizer import select_parents

    assert select_parents([], 2) == []
    fresh = Candidate(id="fresh", technique_id="t", origin="x")
    assert [item.id for item in select_parents([fresh], 2)] == ["fresh"]


@pytest.mark.asyncio
async def test_a_repeated_rewrite_is_discarded_instead_of_re_measured(
    extraction_task, entity_schema, registry
):
    provider = ScriptedProvider(rewrite="SHARPER RULE: copy names verbatim.")
    optimizer = PromptOptimizer(provider)
    technique = registry.technique("structured.schema-first")

    first = await optimizer._propose(
        extraction_task, technique, Candidate(id="p", technique_id="t", origin="x"), None, 4, 30
    )
    assert len(first) == 2  # one rewrite and one append; each duplicate is discarded
    assert {item.origin.split(":")[1] for item in first} == {"rewrite", "append"}
    assert any(
        "already measured" in item or "original" in item for item in optimizer.proposal_failures
    )


def test_brevity_proposals_are_dropped_when_tokens_do_not_matter():
    """Asking for a shorter prompt trades away the thing being optimized."""
    from prompt_selector.domain import Priorities
    from prompt_selector.optimizer import BREVITY_BIAS, mutation_biases

    cost_aware = TaskProfile(
        task_type=TaskType.structured_extraction,
        priorities=Priorities(quality=0.4, reliability=0.3, latency=0.1, token_cost=0.2),
    )
    quality_only = TaskProfile(
        task_type=TaskType.structured_extraction,
        priorities=Priorities(quality=0.8, reliability=0.2, latency=0.0, token_cost=0.0),
    )
    assert BREVITY_BIAS in mutation_biases(cost_aware)
    assert BREVITY_BIAS not in mutation_biases(quality_only)
    assert len(mutation_biases(quality_only)) >= 2


def _report_with(runs):
    from prompt_selector.evals import BenchmarkReport, ExampleRun, build_scorecard

    example_runs = [
        ExampleRun(
            example_id=example_id,
            repeat=0,
            output=output,
            grades={"field_f1": score},
            latency_seconds=0.1,
            prompt_tokens=10,
            completion_tokens=2,
            calls=1,
        )
        for example_id, score, output in runs
    ]
    return BenchmarkReport(
        technique_id="t",
        technique_title="t",
        strategy="single",
        provider="ollama",
        model_id="m",
        task_type="structured_extraction",
        dataset="unit",
        examples=len(example_runs),
        repeats=1,
        started_at="now",
        finished_at="now",
        scorecard=build_scorecard(example_runs, 1),
        runs=example_runs,
    )


def test_skeleton_tells_the_proposer_which_blocks_it_must_not_restate(registry):
    from prompt_selector.optimizer import technique_digest

    digest = technique_digest(registry.technique("structured.schema-first"), "procedure")
    assert "← YOU ARE REWRITING THIS ONE" in digest
    assert digest.count("← YOU ARE REWRITING THIS ONE") == 1
    assert "already states the required output format" in digest
    assert "carries the task input" in digest


def test_tag_digest_ranks_the_weakest_case_types_first(entity_schema):
    from prompt_selector.optimizer import tag_digest

    dataset = [
        BenchmarkExample(id="a", input="x", tags=["demonym"]),
        BenchmarkExample(id="b", input="x", tags=["demonym"]),
        BenchmarkExample(id="c", input="x", tags=["title"]),
    ]
    report = _report_with([("a", 0.0, "{}"), ("b", 0.2, "{}"), ("c", 0.9, "{}")])
    digest = tag_digest(report, dataset)

    assert digest.index("demonym") < digest.index("title")
    assert "0.10" in digest  # the demonym mean
    # A tag that never fails is not worth the proposer's attention.
    perfect = _report_with([("c", 1.0, "{}")])
    assert tag_digest(perfect, dataset) == ""


def test_failure_digest_shows_the_gold_answer(entity_schema):
    """ "wrong content" alone gives the proposer nothing to infer a rule from."""
    from prompt_selector.optimizer import _failure_digest

    dataset = [
        BenchmarkExample(
            id="a",
            input="The Veyrish delegation arrived without Mara.",
            expected={"people": ["Mara"], "places": []},
            tags=["demonym"],
        )
    ]
    report = _report_with([("a", 0.0, '{"people": ["The Veyrish delegation"], "places": []}')])
    digest = _failure_digest(report, dataset)

    assert "[demonym]" in digest
    assert "expected:" in digest and '"Mara"' in digest
    assert "input:" in digest and "Veyrish" in digest
    assert "produced:" in digest
    # Without the dataset it still works, just with less to go on.
    assert "expected:" not in _failure_digest(report, None)


def test_history_digest_ranks_measured_attempts(registry):
    from prompt_selector.optimizer import history_digest

    good = Candidate(id="g", technique_id="t", origin="x", train=card(0.9, 1.0, 100, 1.0))
    good.overlay.block_bodies["procedure"] = "keep titles with names"
    bad = Candidate(id="b", technique_id="t", origin="x", train=card(0.4, 1.0, 100, 1.0))
    bad.overlay.block_bodies["procedure"] = "be helpful"
    plain = Candidate(id="p", technique_id="t", origin="baseline", train=card(0.8, 1.0, 100, 1.0))

    digest = history_digest([bad, good, plain], "procedure")
    assert digest.index("[0.90]") < digest.index("[0.40]")
    # The baseline has no overlay body, so it cannot be "already tried".
    assert digest.count("[") == 2


class SeparateEngineProvider:
    """Records which model each call was made against."""

    def __init__(self, rewrite: str) -> None:
        self.rewrite = rewrite
        self.proposals: list[str] = []
        self.executions: list[str] = []

    async def generate(
        self, prompt: CompiledPrompt, model: ModelProfile, timeout_seconds: float = 120
    ) -> ModelResult:
        if prompt.technique_id == "optimizer.meta":
            self.proposals.append(model.model_id)
            return ModelResult(content=self.rewrite, usage={"prompt_eval_count": 40})
        self.executions.append(model.model_id)
        return ModelResult(content='{"people": [], "places": []}', usage={"eval_count": 5})


@pytest.mark.asyncio
async def test_the_engine_proposes_while_the_target_is_measured(
    extraction_task, entity_schema, registry
):
    target = SeparateEngineProvider(rewrite="RULE: copy names verbatim.")
    engine = SeparateEngineProvider(rewrite="RULE: copy names verbatim.")
    engine_model = ModelProfile(provider="openai", model_id="big-engine", local=False)

    result = await PromptOptimizer(
        provider=target,
        engine_provider=engine,
        engine_model=engine_model,
    ).optimize(
        task=extraction_task,
        technique=registry.technique("structured.schema-first"),
        dataset=dataset(entity_schema),
        rounds=2,
        candidates_per_round=1,
        dataset_name="unit",
    )

    # Proposals went to the engine model only; every measured call used the target.
    assert engine.proposals and set(engine.proposals) == {"big-engine"}
    assert target.proposals == []
    assert set(target.executions) == {"test-model"}
    assert result.engine_model_id == "big-engine"
    assert result.engine_is_target is False
    assert not any("same model the numbers describe" in note for note in result.notes)


@pytest.mark.asyncio
async def test_self_optimization_is_reported_not_hidden(extraction_task, entity_schema, registry):
    provider = ScriptedProvider(rewrite="SHARPER RULE: copy names verbatim.")
    result = await PromptOptimizer(provider).optimize(
        task=extraction_task,
        technique=registry.technique("structured.schema-first"),
        dataset=dataset(entity_schema),
        rounds=2,
        candidates_per_round=1,
        dataset_name="unit",
    )

    assert result.engine_is_target is True
    assert result.engine_model_id == "test-model"
    assert any("same model the numbers describe" in note for note in result.notes)
