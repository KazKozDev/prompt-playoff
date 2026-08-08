import pytest
from conftest import FakeProvider

from prompt_selector.domain import Priorities
from prompt_selector.evals import (
    BenchmarkExample,
    BenchmarkRunner,
    ExampleRun,
    build_scorecard,
    compare_techniques,
)
from prompt_selector.measurements import MeasurementStore


def dataset(schema):
    return [
        BenchmarkExample(
            id="a",
            input="Mara entered Veyr.",
            expected={"people": ["Mara"], "places": ["Veyr"]},
            response_schema=schema,
        ),
        BenchmarkExample(
            id="b",
            input="Orin stayed in Kesh.",
            expected={"people": ["Orin"], "places": ["Kesh"]},
            response_schema=schema,
        ),
    ]


@pytest.mark.asyncio
async def test_benchmark_measures_quality_latency_and_tokens(
    extraction_task, entity_schema, registry
):
    provider = FakeProvider(responses=['{"people": ["Mara"], "places": ["Veyr"]}'])
    report = await BenchmarkRunner(provider).run(
        dataset=dataset(entity_schema),
        task=extraction_task,
        technique=registry.technique("structured.schema-first"),
        dataset_name="unit",
    )
    card = report.scorecard
    assert card.runs == 2
    # Right on the first example, wrong on the second: quality lands between.
    assert 0.0 < card.quality < 1.0
    assert card.contract_pass_rate == 1.0
    assert card.mean_total_tokens == 120
    assert card.mean_calls == 1.0
    assert card.mean_latency_seconds >= 0


@pytest.mark.asyncio
async def test_invalid_json_drives_reliability_to_zero(extraction_task, entity_schema, registry):
    provider = FakeProvider(responses=["Sure! Here is your answer."])
    report = await BenchmarkRunner(provider).run(
        dataset=dataset(entity_schema),
        task=extraction_task,
        technique=registry.technique("structured.schema-first"),
        dataset_name="unit",
    )
    assert report.scorecard.reliability == 0.0
    assert report.scorecard.quality == 0.0
    assert report.runs[0].schema_errors


@pytest.mark.asyncio
async def test_repeats_measure_stability(extraction_task, entity_schema, registry):
    unstable = FakeProvider(
        responses=[
            '{"people": ["Mara"], "places": ["Veyr"]}',
            '{"people": ["Other"], "places": ["Veyr"]}',
        ]
    )
    report = await BenchmarkRunner(unstable).run(
        dataset=dataset(entity_schema)[:1],
        task=extraction_task,
        technique=registry.technique("structured.schema-first"),
        repeats=2,
        dataset_name="unit",
    )
    assert report.repeats == 2
    assert report.scorecard.stability == 0.5
    assert report.scorecard.reliability < report.scorecard.contract_pass_rate


@pytest.mark.asyncio
async def test_multi_call_techniques_report_their_real_cost(
    extraction_task, entity_schema, registry
):
    provider = FakeProvider(responses=['{"people": ["Mara"], "places": ["Veyr"]}'])
    report = await BenchmarkRunner(provider).run(
        dataset=dataset(entity_schema)[:1],
        task=extraction_task,
        technique=registry.technique("structured.few-shot-repair"),
        dataset_name="unit",
    )
    assert report.scorecard.mean_calls == 2.0
    assert report.scorecard.mean_total_tokens == 240


@pytest.mark.asyncio
async def test_comparison_ranks_on_measured_numbers(extraction_task, entity_schema, registry):
    provider = FakeProvider(responses=['{"people": ["Mara"], "places": ["Veyr"]}'])
    task = extraction_task.model_copy(deep=True)
    task.priorities = Priorities(quality=1, reliability=1, latency=0, token_cost=1)
    comparison, reports = await compare_techniques(
        dataset=dataset(entity_schema)[:1],
        task=task,
        techniques=[
            registry.technique("structured.schema-first"),
            registry.technique("structured.few-shot-repair"),
        ],
        provider=provider,
        dataset_name="unit",
    )
    assert len(reports) == 2
    # Same answer from both, but one costs twice the calls, so it must not win.
    assert comparison.winner == "structured.schema-first"
    cheaper = next(e for e in comparison.entries if e.technique_id == "structured.schema-first")
    pricier = next(e for e in comparison.entries if e.technique_id == "structured.few-shot-repair")
    assert cheaper.token_efficiency > pricier.token_efficiency


@pytest.mark.asyncio
async def test_report_converts_to_evidence_and_survives_a_round_trip(
    extraction_task, entity_schema, registry, tmp_path
):
    provider = FakeProvider(responses=['{"people": ["Mara"], "places": ["Veyr"]}'])
    report = await BenchmarkRunner(provider).run(
        dataset=dataset(entity_schema),
        task=extraction_task,
        technique=registry.technique("structured.schema-first"),
        dataset_name="unit",
    )
    store = MeasurementStore(tmp_path / "m.json")
    store.record(report.to_evidence())

    reloaded = MeasurementStore(tmp_path / "m.json")
    found = reloaded.lookup(
        "structured.schema-first",
        extraction_task.task_type,
        extraction_task.model.provider,
        extraction_task.model.model_id,
    )
    assert found is not None
    assert found.quality == report.scorecard.quality
    assert found.examples == 2


def test_scorecard_needs_runs():
    with pytest.raises(ValueError):
        build_scorecard([], 1)


def test_translation_glossary_score_is_a_headline_quality_metric():
    card = build_scorecard(
        [
            ExampleRun(
                example_id="translation-1",
                repeat=0,
                output="",
                grades={"glossary_consistency": 1.0, "omission_check": 1.0},
                latency_seconds=0.1,
                prompt_tokens=1,
                completion_tokens=1,
                calls=1,
            )
        ],
        repeats=1,
    )

    assert card.quality_grader == "glossary_consistency"
    assert card.quality == 1.0


def test_a_measurement_from_another_model_is_not_evidence(tmp_path):
    """A 3B and a 7B model disagree about which technique wins, so a near miss
    must stay a prior rather than silently ranking a model it never ran on."""
    from prompt_selector.domain import MeasuredEvidence, TaskType

    store = MeasurementStore(tmp_path / "m.json")
    store.record(
        MeasuredEvidence(
            technique_id="structured.schema-first",
            task_type=TaskType.structured_extraction,
            provider="ollama",
            model_id="llama3.2:3b",
            quality=0.9,
            reliability=1.0,
            mean_latency_seconds=0.5,
            mean_total_tokens=200,
            examples=40,
            repeats=1,
            dataset="hard",
            recorded_at="2026-08-07T00:00:00+00:00",
        )
    )
    args = ("structured.schema-first", TaskType.structured_extraction, "ollama")
    assert store.lookup(*args, "llama3.2:3b") is not None
    assert store.lookup(*args, "qwen2.5:7b") is None
    assert (
        store.lookup(*args, "llama3.2:3b")
        and store.lookup("other.technique", *args[1:], "llama3.2:3b") is None
    )
