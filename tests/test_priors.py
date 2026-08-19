from pathlib import Path

import pytest

from prompt_playoff.calibration import _task_profile
from prompt_playoff.domain import MeasuredEvidence, ModelClass, TaskType
from prompt_playoff.measurements import MeasurementStore
from prompt_playoff.priors import PriorEstimator, model_class_for
from prompt_playoff.registry import Registry
from prompt_playoff.selector import Selector, _declared_prior

FAST_TECHNIQUE = "reasoning.zero-shot-cot"
SLOW_TECHNIQUE = "reasoning.chain-of-draft"


def _evidence(
    technique_id: str,
    quality: float,
    *,
    task_type: TaskType = TaskType.coding,
    model_id: str = "qwen2.5:7b",
    dataset: str = "inline",
    examples: int = 20,
    repeats: int = 1,
    latency: float = 1.0,
    tokens: float = 100.0,
) -> MeasuredEvidence:
    return MeasuredEvidence(
        technique_id=technique_id,
        task_type=task_type,
        provider="ollama",
        model_id=model_id,
        quality=quality,
        reliability=quality,
        mean_latency_seconds=latency,
        mean_total_tokens=tokens,
        examples=examples,
        repeats=repeats,
        dataset=dataset,
        recorded_at="2026-01-01T00:00:00+00:00",
    )


def _store(tmp_path: Path, records: list[MeasuredEvidence]) -> MeasurementStore:
    store = MeasurementStore(tmp_path / "measurements.json")
    for record in records:
        store.record(record)
    return store


def _estimate(registry: Registry, store: MeasurementStore, technique_id: str, task_type: TaskType):
    technique = registry.technique(technique_id)
    task = _task_profile(task_type, "ollama", "qwen2.5:7b")
    declared = _declared_prior(task, technique)
    return declared, PriorEstimator(store).estimate(technique, task, declared)


def test_winning_a_contest_moves_the_declared_prior_up(registry: Registry, tmp_path: Path) -> None:
    store = _store(
        tmp_path,
        [_evidence(FAST_TECHNIQUE, 0.9), _evidence(SLOW_TECHNIQUE, 0.3)],
    )

    declared, estimate = _estimate(registry, store, FAST_TECHNIQUE, TaskType.coding)

    assert estimate.value > declared
    assert estimate.shift > 0
    assert estimate.measured is True


def test_losing_a_contest_moves_it_down(registry: Registry, tmp_path: Path) -> None:
    store = _store(
        tmp_path,
        [_evidence(FAST_TECHNIQUE, 0.9), _evidence(SLOW_TECHNIQUE, 0.3)],
    )

    declared, estimate = _estimate(registry, store, SLOW_TECHNIQUE, TaskType.coding)

    assert estimate.value < declared


def test_a_technique_measured_with_no_rival_beat_nobody(registry: Registry, tmp_path: Path) -> None:
    """A lone score says as much about the dataset as about the technique."""
    store = _store(tmp_path, [_evidence(FAST_TECHNIQUE, 0.99)])

    declared, estimate = _estimate(registry, store, FAST_TECHNIQUE, TaskType.coding)

    assert estimate.value == declared
    assert estimate.measured is False


def test_scores_from_different_datasets_are_never_averaged_together(
    registry: Registry, tmp_path: Path
) -> None:
    """A kind dataset must not be readable as a good technique."""
    store = _store(
        tmp_path,
        [
            _evidence(FAST_TECHNIQUE, 0.9, dataset="easy"),
            _evidence(SLOW_TECHNIQUE, 0.2, dataset="hard"),
        ],
    )

    declared, estimate = _estimate(registry, store, FAST_TECHNIQUE, TaskType.coding)

    assert estimate.value == declared


def test_a_single_example_run_does_not_move_anything(registry: Registry, tmp_path: Path) -> None:
    store = _store(
        tmp_path,
        [
            _evidence(FAST_TECHNIQUE, 0.99, examples=1, repeats=1),
            _evidence(SLOW_TECHNIQUE, 0.01, examples=1, repeats=1),
        ],
    )

    declared, estimate = _estimate(registry, store, FAST_TECHNIQUE, TaskType.coding)

    assert estimate.value == declared


def test_more_runs_move_the_prior_further(registry: Registry, tmp_path: Path) -> None:
    thin = _store(
        tmp_path / "thin",
        [
            _evidence(FAST_TECHNIQUE, 0.9, examples=4),
            _evidence(SLOW_TECHNIQUE, 0.3, examples=4),
        ],
    )
    thick = _store(
        tmp_path / "thick",
        [
            _evidence(FAST_TECHNIQUE, 0.9, examples=40),
            _evidence(SLOW_TECHNIQUE, 0.3, examples=40),
        ],
    )

    _, thin_estimate = _estimate(registry, thin, FAST_TECHNIQUE, TaskType.coding)
    _, thick_estimate = _estimate(registry, thick, FAST_TECHNIQUE, TaskType.coding)

    #: Compared on the advantage, not the prior: this technique's declared number
    #: is high enough that both land on the ceiling.
    assert thick_estimate.advantage > thin_estimate.advantage


def test_evidence_from_another_task_still_counts_but_counts_less(
    registry: Registry, tmp_path: Path
) -> None:
    """A technique that wins everywhere is a better bet on an unmeasured task."""
    elsewhere = _store(
        tmp_path,
        [
            _evidence(FAST_TECHNIQUE, 0.9, task_type=TaskType.classification),
            _evidence(SLOW_TECHNIQUE, 0.3, task_type=TaskType.classification),
        ],
    )

    declared, estimate = _estimate(registry, elsewhere, FAST_TECHNIQUE, TaskType.coding)

    assert estimate.value > declared
    assert estimate.level == "across every task measured"


def test_efficiency_is_measured_against_the_cheapest_in_the_same_cell(
    registry: Registry, tmp_path: Path
) -> None:
    store = _store(
        tmp_path,
        [
            _evidence(FAST_TECHNIQUE, 0.5, latency=1.0, tokens=100),
            _evidence(SLOW_TECHNIQUE, 0.5, latency=4.0, tokens=400),
        ],
    )

    _, fast = _estimate(registry, store, FAST_TECHNIQUE, TaskType.coding)
    _, slow = _estimate(registry, store, SLOW_TECHNIQUE, TaskType.coding)

    assert fast.latency_efficiency == pytest.approx(1.0)
    assert slow.latency_efficiency == pytest.approx(0.25)
    assert slow.token_efficiency == pytest.approx(0.25)


def test_the_ranking_learns_from_a_model_it_is_not_being_asked_about(
    registry: Registry, tmp_path: Path
) -> None:
    """The point of the whole module: evidence has to cross the cell it was gathered in."""
    task = _task_profile(TaskType.coding, "ollama", "gemma3:4b")
    blank = Selector(registry, None)
    order_before = [item.technique_id for item in blank.rank(task).ranked]

    store = _store(
        tmp_path,
        [
            _evidence(FAST_TECHNIQUE, 0.95, model_id="qwen2.5:7b", examples=40),
            _evidence(SLOW_TECHNIQUE, 0.05, model_id="qwen2.5:7b", examples=40),
        ],
    )
    order_after = [item.technique_id for item in Selector(registry, store).rank(task).ranked]

    assert order_before.index(FAST_TECHNIQUE) > order_before.index(SLOW_TECHNIQUE)
    assert order_after.index(FAST_TECHNIQUE) < order_after.index(SLOW_TECHNIQUE)


def test_an_unmeasured_technique_keeps_the_number_its_author_wrote(
    registry: Registry, tmp_path: Path
) -> None:
    store = _store(
        tmp_path,
        [_evidence(FAST_TECHNIQUE, 0.9), _evidence(SLOW_TECHNIQUE, 0.3)],
    )

    declared, estimate = _estimate(registry, store, "structured.schema-first", TaskType.coding)

    assert estimate.value == declared
    assert "no run yet bears on this technique" in estimate.reason(declared)


def test_model_class_is_read_off_the_parameter_count() -> None:
    assert model_class_for("llama3.2:3b") is ModelClass.small
    assert model_class_for("qwen2.5:7b") is ModelClass.medium
    assert model_class_for("gemma4:31b-cloud") is ModelClass.large
    assert model_class_for("gpt-4.1") is ModelClass.large
