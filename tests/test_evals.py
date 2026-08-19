import asyncio

import pytest
from conftest import FakeProvider

from prompt_playoff.compiler import PromptCompiler
from prompt_playoff.domain import (
    Constraints,
    MeasuredEvidence,
    MeasuredRequest,
    ModelProfile,
    Priorities,
    TaskProfile,
    TaskShape,
    TaskType,
)
from prompt_playoff.evals import (
    BenchmarkExample,
    BenchmarkReport,
    BenchmarkRunner,
    ComparisonReport,
    ExampleRun,
    authored_for,
    build_scorecard,
    compare_techniques,
    prompt_fingerprint,
)
from prompt_playoff.measurements import MeasurementStore


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


def test_a_shape_check_speaks_for_quality_only_when_a_shape_was_required():
    """A technique brings json_validity with it, whatever the task asked for.

    On a prose task that never mentioned JSON, letting it stand as the headline
    would report "quality 0.00" for a model that answered exactly as asked.
    """
    runs = [
        ExampleRun(
            example_id="reply-1",
            repeat=0,
            output="Sorry about that — the refund is on its way.",
            grades={"json_validity": 0.0},
            latency_seconds=0.1,
            prompt_tokens=1,
            completion_tokens=1,
            calls=1,
        )
    ]

    asked = build_scorecard(runs, repeats=1, quality_from_contract=True)
    assert asked.quality_grader == "json_validity"

    unasked = build_scorecard(runs, repeats=1, quality_from_contract=False)
    assert unasked.quality_grader is None
    assert unasked.quality == 0.0
    # The check still ran and still counts against reliability, which is where a
    # contract belongs.
    assert unasked.grades["json_validity"] == 0.0
    assert unasked.contract_pass_rate == 0.0


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
    from prompt_playoff.domain import MeasuredEvidence, TaskType

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


def authored(task, technique, user_input, extra):
    """A prompt as the authoring screen hands it over: compiled, then written on."""
    program = PromptCompiler().compile(task=task, technique=technique, user_input=user_input)
    stage = program.stages[0]
    user = next(message for message in stage.messages if message.role == "user")
    written = stage.model_copy(
        update={
            "messages": [
                message
                if message.role != "user"
                else message.model_copy(update={"content": f"{extra}\n{user.content}"})
                for message in stage.messages
            ]
        }
    )
    return program.model_copy(update={"stages": [written], "source_input": user_input})


@pytest.mark.asyncio
async def test_a_measurement_runs_the_prompt_it_was_given(extraction_task, entity_schema, registry):
    """The screen measures the prompt on Prompt text, not a fresh compile of it.

    An engine model's wording is the difference between the two, so a run that
    quietly recompiled the technique reported numbers for text nobody had seen.
    """
    program = authored(
        extraction_task,
        registry.technique("structured.schema-first"),
        "Mara entered Veyr.",
        "HOUSE RULE: never invent a place.",
    )
    provider = FakeProvider(responses=['{"people": ["Mara"], "places": ["Veyr"]}'])
    report = await BenchmarkRunner(provider).run(
        dataset=dataset(entity_schema),
        task=extraction_task,
        technique=registry.technique("structured.schema-first"),
        dataset_name="unit",
        authored=program,
    )
    sent = [call.messages[-1].content for call in provider.calls]
    assert len(sent) == 2
    # The written line survives every row, and each row's own input replaces the
    # one the prompt was written around.
    assert all("HOUSE RULE: never invent a place." in text for text in sent)
    assert "Mara entered Veyr." in sent[0]
    assert "Orin stayed in Kesh." in sent[1]
    assert "Mara entered Veyr." not in sent[1]
    assert report.prompt_preview["stages"][0]["user"].startswith("HOUSE RULE")


def test_a_reusable_prompt_keeps_its_slot_for_the_row(extraction_task, registry):
    program = authored(
        extraction_task,
        registry.technique("structured.schema-first"),
        "{input}",
        "HOUSE RULE",
    )
    filled = authored_for(program, BenchmarkExample(id="a", input="Orin stayed in Kesh."))
    text = filled.stages[0].messages[-1].content
    assert "Orin stayed in Kesh." in text
    assert "{input}" not in text


def test_a_prompt_with_nowhere_to_put_the_row_says_so(extraction_task, registry):
    """Better a refusal naming the cause than a run measuring the wrong text."""
    program = (
        PromptCompiler()
        .compile(
            task=extraction_task,
            technique=registry.technique("structured.schema-first"),
            user_input="Mara entered Veyr.",
        )
        .model_copy(update={"source_input": ""})
    )
    with pytest.raises(ValueError, match="no place for an example"):
        authored_for(program, BenchmarkExample(id="a", input="Orin stayed in Kesh."))


def test_a_run_records_the_fingerprint_of_the_prompt_it_measured(
    extraction_task, entity_schema, registry
):
    """A release cites a run; this is what makes the citation checkable.

    The release hashes a compiled program and the run used to hash a preview
    with a benchmark row already substituted into it, so no comparison between
    them was possible and any id was as good as any other.
    """
    technique = registry.technique("structured.schema-first")
    authored = PromptCompiler().compile(
        task=extraction_task, technique=technique, user_input="{input}"
    )
    dataset = [
        BenchmarkExample(
            id="ex-1",
            input="Mara visited Veyr.",
            expected={"people": ["Mara"], "places": ["Veyr"]},
            response_schema=entity_schema,
        )
    ]
    runner = BenchmarkRunner(FakeProvider())

    measured = asyncio.run(
        runner.run(
            dataset=dataset,
            task=extraction_task,
            technique=technique,
            dataset_name="unit",
            authored=authored,
        )
    )
    assert measured.authored_hash == prompt_fingerprint(authored)

    # A run of the recipe itself measured nobody's prompt, and says so rather
    # than offering a hash of something that was never supplied.
    compiled_per_row = asyncio.run(
        runner.run(dataset=dataset, task=extraction_task, technique=technique, dataset_name="unit")
    )
    assert compiled_per_row.authored_hash is None


def test_a_comparison_records_the_fingerprint_of_the_arm_that_was_authored():
    """One arm of a comparison is the caller's prompt, and it counts as measured.

    Dropping its fingerprint made every release citing a comparison read as
    "measured something else" — stricter than the truth, and the kind of false
    negative that teaches people to ignore the marker.
    """
    from prompt_playoff.experiments import ExperimentStore

    store = ExperimentStore()
    reports = [
        BenchmarkReport(
            technique_id="direct",
            technique_title="Direct",
            strategy="single",
            provider="ollama",
            model_id="m",
            task_type="structured_extraction",
            dataset="unit",
            examples=1,
            repeats=1,
            started_at="2026-01-01T00:00:00+00:00",
            finished_at="2026-01-01T00:00:01+00:00",
            scorecard=build_scorecard(
                [
                    ExampleRun(
                        example_id="a",
                        repeat=0,
                        output="x",
                        grades={"exact_match": 1.0},
                        latency_seconds=0.1,
                        prompt_tokens=1,
                        completion_tokens=1,
                        calls=1,
                    )
                ],
                1,
            ),
            authored_hash=hash_value,
        )
        for hash_value in (None, "abc123")
    ]
    record = store.add_comparison(
        ComparisonReport(
            dataset="unit",
            model_id="m",
            provider="ollama",
            task_type="structured_extraction",
            repeats=1,
            entries=[],
            winner="direct",
            priorities=Priorities().model_dump(),
        ),
        reports,
        TaskProfile(task_type=TaskType.structured_extraction, model=ModelProfile()),
    )
    assert record.authored_hash == "abc123"


@pytest.mark.asyncio
async def test_a_run_records_the_request_it_measured(
    extraction_task, entity_schema, registry
) -> None:
    """Without this a score is a number about a question nobody wrote down."""
    task = extraction_task.model_copy(update={"shape": {TaskShape.multi_step}})
    report = await BenchmarkRunner(FakeProvider()).run(
        dataset=dataset(entity_schema),
        task=task,
        technique=registry.technique("structured.schema-first"),
        dataset_name="unit",
    )
    evidence = report.to_evidence()

    assert evidence.request is not None
    assert evidence.request.shape == {TaskShape.multi_step}
    assert evidence.request.constraints == task.constraints
    assert evidence.request.fingerprint() == report.request.fingerprint()


def test_two_runs_of_one_technique_asking_different_things_both_survive(tmp_path) -> None:
    """The newer used to erase the older, and they were not the same measurement."""
    store = MeasurementStore(tmp_path / "m.json")
    base = MeasuredEvidence(
        technique_id="direct.explicit-constraints",
        task_type=TaskType.coding,
        provider="ollama",
        model_id="test-model",
        quality=0.8,
        reliability=0.8,
        mean_latency_seconds=1.0,
        mean_total_tokens=100,
        examples=4,
        repeats=1,
        dataset="inline",
        recorded_at="2026-01-01T00:00:00+00:00",
    )
    store.record(base.model_copy(update={"request": MeasuredRequest()}))
    store.record(
        base.model_copy(
            update={
                "request": MeasuredRequest(constraints=Constraints(tools_allowed=True)),
                "quality": 0.2,
            }
        )
    )

    assert len(store.records) == 2
