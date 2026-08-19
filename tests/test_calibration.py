from pathlib import Path

import pytest

from prompt_playoff.calibration import (
    _demonstrated_capabilities,
    _task_profile,
    calibration_payload,
    evaluate,
    outcome,
)
from prompt_playoff.domain import (
    Capability,
    Constraints,
    MeasuredEvidence,
    MeasuredRequest,
    ModelClass,
    TaskShape,
    TaskType,
)
from prompt_playoff.measurements import MeasurementStore
from prompt_playoff.registry import Registry
from prompt_playoff.selector import Selector


def _evidence(
    technique_id: str,
    quality: float,
    *,
    task_type: TaskType = TaskType.structured_extraction,
    model_id: str = "qwen2.5:7b",
    dataset: str = "entity-extraction",
    examples: int = 10,
    repeats: int = 1,
    request: MeasuredRequest | None = None,
) -> MeasuredEvidence:
    return MeasuredEvidence(
        technique_id=technique_id,
        task_type=task_type,
        provider="ollama",
        model_id=model_id,
        quality=quality,
        reliability=quality,
        mean_latency_seconds=1.0,
        mean_total_tokens=100,
        examples=examples,
        repeats=repeats,
        dataset=dataset,
        recorded_at="2026-01-01T00:00:00+00:00",
        request=request,
    )


def _store(tmp_path: Path, records: list[MeasuredEvidence]) -> MeasurementStore:
    store = MeasurementStore(tmp_path / "measurements.json")
    for record in records:
        store.record(record)
    return store


def test_a_cell_with_one_technique_settles_nothing(registry: Registry, tmp_path: Path) -> None:
    report = evaluate(registry, _store(tmp_path, [_evidence("structured.schema-first", 0.9)]))

    assert report.trials == []
    assert report.skipped[0].reason.startswith("1 technique")


def test_techniques_measured_on_different_datasets_are_not_a_contest(
    registry: Registry, tmp_path: Path
) -> None:
    """The first thing this harness caught, and the reason the dataset is in the key."""
    report = evaluate(
        registry,
        _store(
            tmp_path,
            [
                _evidence("structured.schema-first", 0.9, dataset="entity-extraction"),
                _evidence("structured.few-shot-repair", 0.1, dataset="grounded-qa"),
            ],
        ),
    )

    assert report.trials == []


def test_a_run_of_one_example_does_not_decide_a_contest(registry: Registry, tmp_path: Path) -> None:
    report = evaluate(
        registry,
        _store(
            tmp_path,
            [
                _evidence("structured.schema-first", 0.9),
                _evidence("structured.few-shot-repair", 0.99, examples=1, repeats=1),
            ],
        ),
    )

    assert report.trials == []


def test_the_ranking_is_graded_against_the_cell_it_cannot_see(
    registry: Registry, tmp_path: Path
) -> None:
    """Schema-first is the ranking's favourite for extraction; here it loses on the day."""
    report = evaluate(
        registry,
        _store(
            tmp_path,
            [
                _evidence("structured.schema-first", 0.4),
                _evidence("structured.few-shot-repair", 0.9),
            ],
        ),
    )

    trial = report.trials[0]
    assert trial.predicted == "structured.schema-first"
    assert trial.best == "structured.few-shot-repair"
    assert trial.regret == 0.5
    assert report.top1_accuracy == 0.0


def test_naming_the_winner_costs_no_regret(registry: Registry, tmp_path: Path) -> None:
    report = evaluate(
        registry,
        _store(
            tmp_path,
            [
                _evidence("structured.schema-first", 0.9),
                _evidence("structured.few-shot-repair", 0.4),
            ],
        ),
    )

    assert report.trials[0].hit is True
    assert report.mean_regret == 0.0
    assert report.lift == 1.0


def test_lift_is_zero_when_the_ranking_does_what_a_coin_flip_does(
    registry: Registry, tmp_path: Path
) -> None:
    """One cell won, one lost, by the same margin: exactly the coin flip's expectation."""
    report = evaluate(
        registry,
        _store(
            tmp_path,
            [
                _evidence("structured.schema-first", 0.9),
                _evidence("structured.few-shot-repair", 0.5),
                _evidence("structured.schema-first", 0.5, dataset="grounded-qa"),
                _evidence("structured.few-shot-repair", 0.9, dataset="grounded-qa"),
            ],
        ),
    )

    assert report.graded == 2
    assert report.mean_regret == pytest.approx(report.coin_flip_regret)
    assert report.lift == pytest.approx(0.0)


def test_a_hidden_cell_stays_hidden(tmp_path: Path) -> None:
    """Without this the selector reads the answer off the sheet and never errs."""
    store = _store(
        tmp_path,
        [
            _evidence("structured.schema-first", 0.05),
            _evidence("structured.few-shot-repair", 0.95),
        ],
    )
    blind = store.blind_to(TaskType.structured_extraction, "ollama", "qwen2.5:7b")

    assert blind.records == []
    assert len(store.records) == 2


def test_measurements_for_other_models_survive_the_blindfold(tmp_path: Path) -> None:
    store = _store(
        tmp_path,
        [
            _evidence("structured.schema-first", 0.9),
            _evidence("structured.schema-first", 0.9, model_id="llama3.2:3b"),
        ],
    )
    blind = store.blind_to(TaskType.structured_extraction, "ollama", "qwen2.5:7b")

    assert [item.model_id for item in blind.records] == ["llama3.2:3b"]


def test_model_class_is_read_off_the_parameter_count() -> None:
    """A 3B model is not medium, and treating it as one changes which techniques ran."""
    from prompt_playoff.priors import model_class_for

    assert model_class_for("llama3.2:3b") is ModelClass.small
    assert model_class_for("qwen2.5:7b") is ModelClass.medium
    assert model_class_for("gpt-4.1") is ModelClass.large


def test_outcome_weighs_quality_and_reliability_equally() -> None:
    assert outcome(_evidence("any", 0.5)) == 0.5


def test_the_payload_carries_every_graded_contest(registry: Registry, tmp_path: Path) -> None:
    report = evaluate(
        registry,
        _store(
            tmp_path,
            [
                _evidence("structured.schema-first", 0.4),
                _evidence("structured.few-shot-repair", 0.9),
            ],
        ),
    )
    payload = calibration_payload(report)

    assert payload["summary"]["cells_graded"] == 1
    assert payload["trials"][0]["regret"] == 0.5
    assert len(payload["trials"][0]["entrants"]) == 2


def test_the_stated_confidence_is_graded_against_the_pair_it_was_about(
    registry: Registry, tmp_path: Path
) -> None:
    report = evaluate(
        registry,
        _store(
            tmp_path,
            [
                _evidence("structured.schema-first", 0.4),
                _evidence("structured.few-shot-repair", 0.9),
            ],
        ),
    )
    trial = report.trials[0]

    assert 0 < trial.confidence < 1
    assert trial.pairwise_hit is False
    assert report.calibration_error == pytest.approx(trial.confidence - 0.0)


def test_confidence_stays_calibrated_on_the_real_measurement_store() -> None:
    """The one assertion that would catch confidence drifting back into decoration."""
    from prompt_playoff.measurements import MeasurementStore

    report = evaluate(Registry.load(), MeasurementStore())

    if report.graded >= 10:
        assert abs(report.calibration_error) < 0.15


def _request(**overrides) -> MeasuredRequest:
    return MeasuredRequest(
        shape=overrides.pop("shape", set()),
        complexity=overrides.pop("complexity", "medium"),
        constraints=Constraints(**overrides),
    )


def test_runs_that_answered_different_questions_are_not_a_contest(
    registry: Registry, tmp_path: Path
) -> None:
    """Same rows, same model, one run with tools and one without: two questions."""
    report = evaluate(
        registry,
        _store(
            tmp_path,
            [
                _evidence("structured.schema-first", 0.9, request=_request(tools_allowed=True)),
                _evidence("structured.few-shot-repair", 0.1, request=_request()),
            ],
        ),
    )

    assert report.trials == []


def test_a_recorded_shape_is_replayed_rather_than_reconstructed(
    registry: Registry, tmp_path: Path
) -> None:
    request = _request(shape={TaskShape.multi_step, TaskShape.high_stakes})
    report = evaluate(
        registry,
        _store(
            tmp_path,
            [
                _evidence("structured.schema-first", 0.9, request=request),
                _evidence("structured.few-shot-repair", 0.4, request=request),
            ],
        ),
    )

    assert report.trials[0].request_recorded is True
    assert report.with_recorded_request == 1


def test_older_records_are_still_graded_and_counted_apart(
    registry: Registry, tmp_path: Path
) -> None:
    report = evaluate(
        registry,
        _store(
            tmp_path,
            [
                _evidence("structured.schema-first", 0.9),
                _evidence("structured.few-shot-repair", 0.4),
            ],
        ),
    )

    assert report.graded == 1
    assert report.with_recorded_request == 0


def test_a_capability_a_technique_needed_is_a_capability_the_model_had(
    registry: Registry,
) -> None:
    """react needs tool calling; it was benchmarked, so the model plainly had it.

    Declaring a cautious pair of capabilities ruled it ineligible and handed an
    agents contest to a technique that had lost it — a result decided by the
    harness rather than by the ranking under test.
    """
    entrants = {"agents.react": 0.9, "reasoning.decomposition": 0.2}
    capabilities = _demonstrated_capabilities(registry, entrants)
    task = _task_profile(TaskType.agents, "ollama", "qwen2.5:7b", capabilities=capabilities)
    ranked = Selector(registry, None).rank(task)

    assert Capability.tool_calling in capabilities
    assert "agents.react" in {item.technique_id for item in ranked.ranked}


def test_an_id_the_registry_no_longer_carries_is_simply_skipped(registry: Registry) -> None:
    assert _demonstrated_capabilities(registry, {"gone.forever": 0.5})
