"""Grade the ranking against measurements it was not allowed to see.

Every weight in :mod:`prompt_playoff.selector` was set by hand, and each one was
a reaction to a case someone noticed: a two-stage recipe winning a one-line
request, a common trait outranking a rare one. That is a reasonable way to start
and a bad way to continue, because nothing in the project could answer the only
question that matters — when the selector names a technique, how much worse is
it than the one that actually won?

This module answers it without spending a single model call, because the answer
is already on disk. Wherever the measurement store holds two or more techniques
benchmarked on the same task and the same model, that cell is a settled contest
with a known winner. Hide the cell, ask the selector to rank blind, and compare.

Three numbers come out, and the third is the one to watch:

    top-1 accuracy   how often the ranking's favourite really won
    mean regret      how much outcome is lost by following the ranking
    coin-flip regret how much is lost by picking one of the measured
                     techniques at random

A selector whose regret matches the coin flip knows nothing, whatever its
accuracy looks like on a cell where two techniques were tied anyway. The gap
between those two numbers is the entire value of the ranking, stated in the
units the benchmark already measures.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from prompt_playoff.domain import (
    Capability,
    Constraints,
    MeasuredEvidence,
    MeasuredRequest,
    ModelProfile,
    Priorities,
    Recommendation,
    TaskProfile,
    TaskType,
)
from prompt_playoff.measurements import MeasurementStore, request_fingerprint
from prompt_playoff.priors import model_class_for
from prompt_playoff.registry import Registry, RegistryError
from prompt_playoff.selector import Selector, _beats

#: A cell needs at least this many measured techniques to settle anything. Two is
#: enough for a contest; one is a data point with nobody to lose to.
MIN_TECHNIQUES = 2

#: Runs behind a number before it is allowed to decide a contest. A single example
#: run once is a coin landing, not a measurement, and the store is full of them
#: from smoke tests and one-row uploads.
MIN_RUNS = 4


def outcome(evidence: MeasuredEvidence) -> float:
    """What the benchmark says the technique was worth, in one number.

    Quality and reliability weighted equally, on purpose: the grading objective
    has to be fixed across cells, and a per-task weighting would let the grade
    move for reasons that have nothing to do with the ranking under test.
    """
    return (evidence.quality + evidence.reliability) / 2


@dataclass(frozen=True)
class Trial:
    """One settled contest, and where the blind ranking placed its entrants."""

    task_type: TaskType
    provider: str
    model_id: str
    dataset: str
    #: Whether the runs recorded the request they answered, or the profile behind
    #: this contest had to be reconstructed from the task type alone.
    request_recorded: bool
    #: Measured techniques in this cell, best first.
    entrants: list[tuple[str, float]]
    #: The measured technique the ranking put highest.
    predicted: str
    predicted_outcome: float
    best: str
    best_outcome: float
    #: Where the real winner landed among the measured entrants, 1 being first.
    rank_of_best: int
    #: What the selector claimed about its own pick beating the next one it liked.
    confidence: float
    #: Whether it did. The pair the confidence was about, and nothing wider — a
    #: stated probability is only checkable against the question it answered.
    pairwise_hit: bool

    @property
    def regret(self) -> float:
        return self.best_outcome - self.predicted_outcome

    @property
    def hit(self) -> bool:
        return self.predicted == self.best

    @property
    def coin_flip_regret(self) -> float:
        """Expected regret from picking one measured technique uniformly at random."""
        mean_outcome = statistics.fmean(value for _, value in self.entrants)
        return self.best_outcome - mean_outcome

    @property
    def spread(self) -> float:
        """Best minus worst. A cell with no spread cannot reward getting it right."""
        return self.best_outcome - min(value for _, value in self.entrants)


@dataclass(frozen=True)
class Skip:
    task_type: TaskType
    provider: str
    model_id: str
    dataset: str
    reason: str


@dataclass(frozen=True)
class CalibrationReport:
    trials: list[Trial] = field(default_factory=list)
    skipped: list[Skip] = field(default_factory=list)

    @property
    def graded(self) -> int:
        return len(self.trials)

    @property
    def top1_accuracy(self) -> float:
        if not self.trials:
            return 0.0
        return sum(1 for trial in self.trials if trial.hit) / len(self.trials)

    @property
    def mean_regret(self) -> float:
        if not self.trials:
            return 0.0
        return statistics.fmean(trial.regret for trial in self.trials)

    @property
    def max_regret(self) -> float:
        return max((trial.regret for trial in self.trials), default=0.0)

    @property
    def coin_flip_regret(self) -> float:
        if not self.trials:
            return 0.0
        return statistics.fmean(trial.coin_flip_regret for trial in self.trials)

    @property
    def with_recorded_request(self) -> int:
        """Contests where the request was on record rather than reconstructed."""
        return sum(1 for trial in self.trials if trial.request_recorded)

    @property
    def mean_confidence(self) -> float:
        if not self.trials:
            return 0.0
        return statistics.fmean(trial.confidence for trial in self.trials)

    @property
    def pairwise_accuracy(self) -> float:
        """How often the pick really did beat the runner-up it was compared against."""
        if not self.trials:
            return 0.0
        return sum(1 for trial in self.trials if trial.pairwise_hit) / len(self.trials)

    @property
    def calibration_error(self) -> float:
        """Claimed confidence minus what happened. Positive means overconfident."""
        return self.mean_confidence - self.pairwise_accuracy

    @property
    def mean_rank_of_best(self) -> float:
        if not self.trials:
            return 0.0
        return statistics.fmean(trial.rank_of_best for trial in self.trials)

    @property
    def lift(self) -> float:
        """The share of the coin flip's regret the ranking avoids.

        1.0 means it names the winner every time; 0.0 means it is a coin flip
        with extra steps; below 0.0 means following it is worse than not.
        """
        baseline = self.coin_flip_regret
        if baseline <= 0:
            return 0.0
        return (baseline - self.mean_regret) / baseline

    def summary(self) -> dict[str, float | int]:
        return {
            "cells_graded": self.graded,
            "cells_skipped": len(self.skipped),
            "with_recorded_request": self.with_recorded_request,
            "top1_accuracy": round(self.top1_accuracy, 4),
            "mean_regret": round(self.mean_regret, 4),
            "max_regret": round(self.max_regret, 4),
            "coin_flip_regret": round(self.coin_flip_regret, 4),
            "lift": round(self.lift, 4),
            "mean_rank_of_best": round(self.mean_rank_of_best, 3),
            "mean_confidence": round(self.mean_confidence, 4),
            "pairwise_accuracy": round(self.pairwise_accuracy, 4),
            "calibration_error": round(self.calibration_error, 4),
        }


def calibration_payload(report: CalibrationReport) -> dict[str, object]:
    """The report as plain data, for `--json` and for anything that wants to diff runs."""
    return {
        "summary": report.summary(),
        "trials": [
            {
                "task_type": trial.task_type.value,
                "provider": trial.provider,
                "model_id": trial.model_id,
                "dataset": trial.dataset,
                "request_recorded": trial.request_recorded,
                "predicted": trial.predicted,
                "predicted_outcome": round(trial.predicted_outcome, 4),
                "best": trial.best,
                "best_outcome": round(trial.best_outcome, 4),
                "regret": round(trial.regret, 4),
                "rank_of_best": trial.rank_of_best,
                "confidence": round(trial.confidence, 4),
                "pairwise_hit": trial.pairwise_hit,
                "entrants": [
                    {"technique_id": name, "outcome": round(value, 4)}
                    for name, value in trial.entrants
                ],
            }
            for trial in report.trials
        ],
        "skipped": [
            {
                "task_type": skip.task_type.value,
                "provider": skip.provider,
                "model_id": skip.model_id,
                "dataset": skip.dataset,
                "reason": skip.reason,
            }
            for skip in report.skipped
        ],
    }


def evaluate(
    registry: Registry,
    measurements: MeasurementStore,
    min_techniques: int = MIN_TECHNIQUES,
    min_runs: int = MIN_RUNS,
) -> CalibrationReport:
    """Rank every settled cell blind and report how well the ranking did."""
    trials: list[Trial] = []
    skipped: list[Skip] = []

    for (task_type, provider, model_id, dataset, _), records in _cells(measurements).items():
        entrants = _entrants(records, min_runs)
        request = next((item.request for item in records if item.request is not None), None)
        if len(entrants) < min_techniques:
            skipped.append(
                Skip(
                    task_type,
                    provider,
                    model_id,
                    dataset,
                    f"{len(entrants)} technique(s) measured on at least {min_runs} runs",
                )
            )
            continue

        task = _task_profile(
            task_type,
            provider,
            model_id,
            request,
            capabilities=_demonstrated_capabilities(registry, entrants),
        )
        blind = Selector(registry, measurements.blind_to(task_type, provider, model_id))
        ranked = blind.rank(task).ranked

        placed = [item.technique_id for item in ranked if item.technique_id in entrants]
        if not placed:
            skipped.append(
                Skip(
                    task_type,
                    provider,
                    model_id,
                    dataset,
                    "the ranking found none of the measured techniques eligible",
                )
            )
            continue

        best, best_outcome = max(entrants.items(), key=lambda item: item[1])
        predicted = placed[0]
        confidence, pairwise_hit = _pairwise(ranked, placed, entrants)
        trials.append(
            Trial(
                task_type=task_type,
                provider=provider,
                model_id=model_id,
                dataset=dataset,
                request_recorded=request is not None,
                entrants=sorted(entrants.items(), key=lambda item: item[1], reverse=True),
                predicted=predicted,
                predicted_outcome=entrants[predicted],
                best=best,
                best_outcome=best_outcome,
                rank_of_best=placed.index(best) + 1 if best in placed else len(placed) + 1,
                confidence=confidence,
                pairwise_hit=pairwise_hit,
            )
        )

    trials.sort(key=lambda trial: (-trial.regret, trial.model_id, trial.task_type.value))
    skipped.sort(key=lambda skip: (skip.model_id, skip.task_type.value))
    return CalibrationReport(trials=trials, skipped=skipped)


def _pairwise(
    ranked: list[Recommendation],
    placed: list[str],
    entrants: dict[str, float],
) -> tuple[float, bool]:
    """What the selector claimed about its top two, and whether it held.

    Confidence is a statement about one pair — take this, or take the next — so it
    is graded against that pair and no other. Comparing it to "was this the best of
    twelve" would mark a well-calibrated number wrong.
    """
    if len(placed) < 2:
        return 0.98, True
    scored = {item.technique_id: item for item in ranked}
    top, rival = scored[placed[0]], scored[placed[1]]
    return _beats(top, rival), entrants[placed[0]] >= entrants[placed[1]]


def _cells(
    measurements: MeasurementStore,
) -> dict[tuple[TaskType, str, str, str, str], list[MeasuredEvidence]]:
    """Contests, keyed by everything that has to match for a comparison to mean anything.

    The dataset belongs in the key, and leaving it out was the first thing this
    module caught: the store held one technique measured on `entity-extraction`
    and another on `agents` under the same task and model, and ranking them
    against each other read a difference in the data as a difference in the
    technique. The request belongs there for the same reason — a run that allowed
    tools and a run that did not answered different questions — and runs recorded
    before the store kept the request group together under `unrecorded`, which is
    what they always did.
    """
    cells: dict[tuple[TaskType, str, str, str, str], list[MeasuredEvidence]] = {}
    for record in measurements.records:
        key = (
            record.task_type,
            record.provider,
            record.model_id,
            record.dataset,
            request_fingerprint(record),
        )
        cells.setdefault(key, []).append(record)
    return cells


def _entrants(records: list[MeasuredEvidence], min_runs: int) -> dict[str, float]:
    """One outcome per technique: the run with the most examples behind it."""
    best_run: dict[str, MeasuredEvidence] = {}
    for record in records:
        if record.examples * record.repeats < min_runs:
            continue
        seen = best_run.get(record.technique_id)
        weight = record.examples * record.repeats
        if seen is None or weight > seen.examples * seen.repeats:
            best_run[record.technique_id] = record
    return {technique_id: outcome(record) for technique_id, record in best_run.items()}


def _demonstrated_capabilities(registry: Registry, entrants: dict[str, float]) -> set[Capability]:
    """What the model provably has, because techniques needing it ran on it.

    The store keeps a provider and an id, so the model's declared capabilities have
    to come from somewhere, and declaring a cautious pair of them quietly threw the
    contest: `agents.react` needs tool calling, was ruled ineligible for want of it,
    and lost an agents contest it had in fact won. A technique that produced a
    measurement met its own requirements by definition. That is not an inference
    about the model, it is a reading of what already happened.
    """
    demonstrated = {Capability.system_messages, Capability.structured_output}
    for technique_id in entrants:
        try:
            demonstrated |= registry.technique(technique_id).required_capabilities
        except RegistryError:
            #: Measured under an id this registry no longer carries. Nothing to read.
            continue
    return demonstrated


def _task_profile(
    task_type: TaskType,
    provider: str,
    model_id: str,
    request: MeasuredRequest | None = None,
    capabilities: set[Capability] | None = None,
) -> TaskProfile:
    """The request a benchmark run answered, from the record where there is one.

    Runs now carry the shape and constraints they ran under, so this replays them
    rather than reconstructing them. The reconstruction below is what the older
    hundred-odd records still get, and it is deliberately thin: shape stays empty
    rather than invented, because reading a request out of a task type is the
    guessing this whole exercise exists to remove.

    Priorities are the exception, and they are not replayed, they are pinned: the
    grade is quality and reliability, so the request put to the selector has to ask
    for quality and reliability and nothing else. Leaving the defaults in place
    asked it for a technique that is also fast and cheap and then marked it down
    for delivering one — which is how better latency data first made the ranking
    look worse.
    """
    quality_only = Priorities(quality=0.5, reliability=0.5, latency=0.0, token_cost=0.0)
    if request is not None:
        return TaskProfile(
            task_type=task_type,
            complexity=request.complexity,
            shape=set(request.shape),
            output_contract="json_schema" if request.constraints.strict_json else "free_text",
            priorities=quality_only,
            constraints=request.constraints,
            model=_model_profile(provider, model_id, capabilities),
        )

    strict_json = task_type is TaskType.structured_extraction
    return TaskProfile(
        task_type=task_type,
        output_contract="json_schema" if strict_json else "free_text",
        priorities=quality_only,
        constraints=Constraints(
            strict_json=strict_json,
            requires_validation=strict_json or task_type is TaskType.coding,
            supplied_material=True,
            #: Not an inference from the request — a fact about the task type. An
            #: agents task is tool use; a run of one with tools forbidden would
            #: have had nothing to measure.
            tools_allowed=task_type is TaskType.agents,
        ),
        model=_model_profile(provider, model_id, capabilities),
    )


def _model_profile(
    provider: str, model_id: str, capabilities: set[Capability] | None = None
) -> ModelProfile:
    """The model as the selector would have seen it during the run.

    Capabilities come from what the runs demonstrated; class is read off the
    parameter count in the id. Both are reconstructions — the store keeps a
    provider and an id, nothing else — but either one guessed low silently
    disqualifies techniques that in fact ran, which is a contest decided by the
    harness rather than by the ranking.
    """
    return ModelProfile(
        provider=provider,
        model_id=model_id,
        model_class=model_class_for(model_id),
        local=provider == "ollama",
        capabilities=capabilities or {Capability.system_messages, Capability.structured_output},
    )
