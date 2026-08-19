"""What a technique is worth on a task, from every run that bears on it.

Until now the answer came out of the technique's own YAML: `task:coding: 0.84`,
written by whoever added the file, blended with three sibling numbers under fixed
weights. It never moved, however many benchmarks were run, unless somebody edited
the file. A tool whose whole claim is that it measures should not keep its
opinions in a place measurement cannot reach.

Two things make this harder than averaging.

The first is that a raw score is not comparable across datasets. Schema-first
scoring 0.93 on `entity-extraction` and few-shot-repair scoring 0.75 on
`grounded-qa` says nothing about which is better; it says one dataset is kinder
than the other. So nothing here averages scores. Every run is first turned into
an *advantage* — how far above or below the other techniques measured on exactly
the same task, model and rows it landed — and advantages are comparable because
the thing they are measured against is held fixed.

The second is that there is almost no data. Sixty-one techniques against nine
task types and nine models is five thousand cells, and roughly a hundred runs
exist. Any cell read on its own is noise. So the estimate is built coarse to
fine — what this technique does in general, then on this task, then on this size
of model — and each step is allowed to move the previous one only as far as its
own evidence justifies. Two runs nudge; forty decide. This is ordinary shrinkage,
and it is the reason a single lucky benchmark cannot promote a technique to the
top of a task it has never been suited for.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from prompt_playoff.domain import MeasuredEvidence, ModelClass, TaskProfile, TaskType, TechniqueSpec
from prompt_playoff.measurements import MeasurementStore

#: Runs of evidence needed at a level before it outweighs the level above it.
#: Eight is roughly the point where a benchmark on this project stops being a
#: mood: below it a level nudges its parent, above it the level takes over.
PSEUDO_RUNS = 8.0

#: No single run may count for more than this, however many examples it had. One
#: 120-example sweep is worth more than one 6-example probe and not worth more
#: than every other measurement of the technique put together.
RUN_CAP = 40.0

#: A contest needs a rival before an advantage means anything.
MIN_RIVALS = 2

#: Runs behind a number before it may contribute. Mirrors the calibration
#: harness: a single example run once is a coin landing.
MIN_RUNS = 4


def outcome(evidence: MeasuredEvidence) -> float:
    return (evidence.quality + evidence.reliability) / 2


@dataclass(frozen=True)
class Estimate:
    """A prior and the evidence that moved it, in the words the reasons will use."""

    value: float
    #: Runs of measured evidence that bear on this technique and task at all.
    runs: float
    #: How far the measurements moved the declared number, signed.
    shift: float
    #: The shrunk advantage itself, before it was added to anything. Declared
    #: quality and reliability are wrong by about this much too, and every place
    #: the ranking reads them should hear about it — otherwise the evidence lands
    #: in one term worth 0.13 while the author's guesses keep three worth more.
    advantage: float
    #: The finest level that had anything to say.
    level: str
    #: Measured latency and token efficiency, on the same relative scale the
    #: declared characteristics use: 1.0 is the cheapest technique in its cell.
    #: None where no run bears on it.
    latency_efficiency: float | None = None
    token_efficiency: float | None = None

    @property
    def measured(self) -> bool:
        return self.runs > 0

    def reason(self, declared: float) -> str:
        if not self.measured:
            return f"Declared prior {self.value:.2f}; no run yet bears on this technique."
        direction = "up" if self.shift >= 0 else "down"
        return (
            f"Prior {self.value:.2f}: declared {declared:.2f}, moved {direction} by "
            f"{abs(self.shift):.2f} on {self.runs:.0f} runs of evidence "
            f"({self.level})."
        )


@dataclass(frozen=True)
class _Level:
    """One aggregation of advantages: how much better than its rivals, on what."""

    advantage: float
    weight: float


class PriorEstimator:
    """Reads the measurement store once, then answers per (technique, task).

    Built per selection, because the store it reads may be a blindfolded view of
    itself — the calibration harness hides the cell it is grading, and an estimator
    that cached across those would be grading itself on its own answers.
    """

    def __init__(
        self,
        measurements: MeasurementStore | None = None,
        pseudo_runs: float = PSEUDO_RUNS,
        min_runs: int = MIN_RUNS,
    ) -> None:
        self.pseudo_runs = pseudo_runs
        self._by_technique: dict[str, _Level] = {}
        self._by_task: dict[tuple[str, TaskType], _Level] = {}
        self._by_class: dict[tuple[str, TaskType, ModelClass], _Level] = {}
        #: Efficiency needs no advantage trick: a run's latency divided by the
        #: fastest latency in its own cell is already relative, and already on the
        #: scale the technique files declare. So these hold the ratios themselves.
        self._latency: dict[tuple[str, TaskType], _Level] = {}
        self._tokens: dict[tuple[str, TaskType], _Level] = {}
        if measurements is not None:
            self._ingest(measurements, min_runs)

    def estimate(self, technique: TechniqueSpec, task: TaskProfile, declared: float) -> Estimate:
        """The declared prior, moved by measured advantage, coarse level to fine."""
        advantage = 0.0
        runs = 0.0
        level = "declared"
        for name, found in (
            ("across every task measured", self._by_technique.get(technique.id)),
            ("on this task type", self._by_task.get((technique.id, task.task_type))),
            (
                "on this task type and model class",
                self._by_class.get((technique.id, task.task_type, task.model.model_class)),
            ),
        ):
            if found is None or found.weight <= 0:
                continue
            share = found.weight / (found.weight + self.pseudo_runs)
            advantage += share * (found.advantage - advantage)
            runs = max(runs, found.weight)
            level = name
        value = min(1.0, max(0.0, declared + advantage))
        key = (technique.id, task.task_type)
        return Estimate(
            value=value,
            runs=runs,
            shift=value - declared,
            advantage=advantage,
            level=level,
            latency_efficiency=_observed(self._latency.get(key)),
            token_efficiency=_observed(self._tokens.get(key)),
        )

    def shrink_toward(self, declared: float, observed: float | None, runs: float) -> float:
        """Move a declared number toward what was measured, as far as the runs allow."""
        if observed is None or runs <= 0:
            return declared
        share = runs / (runs + self.pseudo_runs)
        return declared + share * (observed - declared)

    def _ingest(self, measurements: MeasurementStore, min_runs: int) -> None:
        cells: dict[tuple[TaskType, str, str, str], list[MeasuredEvidence]] = defaultdict(list)
        for record in measurements.records:
            if record.examples * record.repeats < min_runs:
                continue
            cells[(record.task_type, record.provider, record.model_id, record.dataset)].append(
                record
            )

        latency: dict[tuple[str, TaskType], list[tuple[float, float]]] = defaultdict(list)
        tokens: dict[tuple[str, TaskType], list[tuple[float, float]]] = defaultdict(list)
        by_technique: dict[str, list[tuple[float, float]]] = defaultdict(list)
        by_task: dict[tuple[str, TaskType], list[tuple[float, float]]] = defaultdict(list)
        by_class: dict[tuple[str, TaskType, ModelClass], list[tuple[float, float]]] = defaultdict(
            list
        )

        for (task_type, _, model_id, _), records in cells.items():
            best = _best_per_technique(records)
            if len(best) < MIN_RIVALS:
                #: One technique measured alone beat nobody. Its score is a fact
                #: about the dataset as much as about the technique.
                continue
            mean = sum(outcome(item) for item in best.values()) / len(best)
            model_class = model_class_for(model_id)
            fastest = _cheapest(item.mean_latency_seconds for item in best.values())
            leanest = _cheapest(item.mean_total_tokens for item in best.values())
            for technique_id, record in best.items():
                advantage = outcome(record) - mean
                weight = min(float(record.examples * record.repeats), RUN_CAP)
                by_technique[technique_id].append((advantage, weight))
                by_task[(technique_id, task_type)].append((advantage, weight))
                by_class[(technique_id, task_type, model_class)].append((advantage, weight))
                if fastest is not None and record.mean_latency_seconds > 0:
                    latency[(technique_id, task_type)].append(
                        (min(1.0, fastest / record.mean_latency_seconds), weight)
                    )
                if leanest is not None and record.mean_total_tokens > 0:
                    tokens[(technique_id, task_type)].append(
                        (min(1.0, leanest / record.mean_total_tokens), weight)
                    )

        self._by_technique = {key: _combine(values) for key, values in by_technique.items()}
        self._by_task = {key: _combine(values) for key, values in by_task.items()}
        self._by_class = {key: _combine(values) for key, values in by_class.items()}
        self._latency = {key: _combine(values) for key, values in latency.items()}
        self._tokens = {key: _combine(values) for key, values in tokens.items()}


def _observed(level: _Level | None) -> float | None:
    return None if level is None or level.weight <= 0 else level.advantage


def _cheapest(values) -> float | None:
    positive = [value for value in values if value > 0]
    return min(positive) if positive else None


def _best_per_technique(records: list[MeasuredEvidence]) -> dict[str, MeasuredEvidence]:
    best: dict[str, MeasuredEvidence] = {}
    for record in records:
        seen = best.get(record.technique_id)
        if seen is None or record.examples * record.repeats > seen.examples * seen.repeats:
            best[record.technique_id] = record
    return best


def _combine(values: list[tuple[float, float]]) -> _Level:
    weight = sum(item[1] for item in values)
    if weight <= 0:
        return _Level(advantage=0.0, weight=0.0)
    return _Level(
        advantage=sum(advantage * item_weight for advantage, item_weight in values) / weight,
        weight=weight,
    )


#: Parameter counts, read off the model id, that mark the boundaries between the
#: classes techniques declare themselves for.
_SMALL_BILLIONS = 5
_MEDIUM_BILLIONS = 30


def model_class_for(model_id: str) -> ModelClass:
    """The class a model id implies, for grouping evidence and for replaying a run.

    A measurement records a provider and an id and nothing else, so both this
    module and the calibration harness have to reconstruct the rest. They read it
    the same way on purpose: a 3B model graded as medium would be judged against
    techniques that never ran on it.
    """
    match = re.search(r"(\d+(?:\.\d+)?)\s*b\b", model_id.lower())
    if match is None:
        #: No parameter count in the id is how hosted frontier models look.
        return ModelClass.large
    billions = float(match.group(1))
    if billions < _SMALL_BILLIONS:
        return ModelClass.small
    if billions < _MEDIUM_BILLIONS:
        return ModelClass.medium
    return ModelClass.large
