from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from prompt_selector.domain import (
    Capability,
    EvidenceLevel,
    MeasuredEvidence,
    Recommendation,
    Rejection,
    ScoreBreakdown,
    SelectionResult,
    TaskProfile,
    TaskShape,
    TaskType,
    TechniqueSpec,
)
from prompt_selector.measurements import MeasurementStore
from prompt_selector.registry import Registry

EVIDENCE_SCORES = {
    EvidenceLevel.heuristic: 0.35,
    EvidenceLevel.documented: 0.58,
    EvidenceLevel.benchmarked: 0.78,
    EvidenceLevel.replicated: 0.95,
}

#: Task types that transform something the prompt has to carry. Asked without it,
#: the request is a topic, and the best any recipe can do is say so.
_NEEDS_MATERIAL = {TaskType.summarization, TaskType.translation, TaskType.structured_extraction}

#: What one extra model call costs a technique, by how much work the task is.
CALL_COST = {"low": 0.09, "medium": 0.065, "high": 0.03}

#: What it costs once the request is genuinely made of steps: little.
STEPPED_CALL_COST = 0.015


def _call_cost(task: TaskProfile) -> float:
    if TaskShape.multi_step in task.shape:
        return STEPPED_CALL_COST
    return CALL_COST.get(task.complexity, CALL_COST["medium"])


def _shape_weights(techniques: Iterable[TechniqueSpec]) -> dict[TaskShape, float]:
    """How much one trait is worth: the rarer the claim, the more it separates.

    Eight of the recipes call themselves good for verifiable work and two for work
    that comes with examples. Counting matches alone would make the common claim
    worth as much as the rare one, and every request that mentions correctness
    would end in a tie broken by static priors — which is how one technique came
    to win a whole task type.
    """
    counts = Counter(trait for technique in techniques for trait in technique.suits)
    return {trait: 1.0 / max(counts.get(trait, 0), 1) for trait in TaskShape}


def _shape_fit(
    shape: set[TaskShape], suits: set[TaskShape], weights: dict[TaskShape, float]
) -> float:
    """The share of this request's traits, by weight, that the recipe is built for."""
    if not shape:
        return 0.5
    total = sum(weights[trait] for trait in shape)
    if not total:
        return 0.5
    return sum(weights[trait] for trait in shape & suits) / total


@dataclass(frozen=True)
class _Scored:
    technique: TechniqueSpec
    recommendation: Recommendation


@dataclass(frozen=True)
class _Reference:
    """Best measured cost in the candidate set, used to make efficiencies relative."""

    latency_seconds: float | None = None
    total_tokens: float | None = None


class Selector:
    def __init__(self, registry: Registry, measurements: MeasurementStore | None = None) -> None:
        self.registry = registry
        self.measurements = measurements

    def select(self, task: TaskProfile, limit: int = 3) -> SelectionResult:
        eligible: list[TechniqueSpec] = []
        rejected: list[Rejection] = []

        for technique in self.registry.techniques.values():
            reasons = self._rejection_reasons(task, technique)
            if reasons:
                rejected.append(
                    Rejection(
                        technique_id=technique.id,
                        title=technique.title,
                        reasons=reasons,
                    )
                )
                continue
            eligible.append(technique)

        measured = {technique.id: self._measurement(task, technique) for technique in eligible}
        reference = _reference_costs(measured.values())
        weights = _shape_weights(self.registry.techniques.values())

        candidates = [
            _Scored(
                technique,
                self._score(
                    task,
                    technique,
                    measured.get(technique.id),
                    reference,
                    _shape_fit(task.shape, technique.suits, weights),
                ),
            )
            for technique in eligible
        ]
        candidates.sort(key=lambda item: item.recommendation.score, reverse=True)
        selected = self._diverse_top(candidates, limit)
        selected = self._apply_confidence(selected, candidates)

        warnings: list[str] = []
        if not selected:
            warnings.append("No technique satisfies all hard constraints.")
        elif selected[0].recommendation.confidence < 0.55:
            warnings.append("Recommendation confidence is low; run a task-specific benchmark.")
        if not any(item.recommendation.evidence_source == "measured" for item in selected):
            warnings.append(
                "No measured benchmark exists for this model yet; ranking uses declared priors. "
                "Run a benchmark on the compiled prompt to replace them with real numbers."
            )
        if (
            task.constraints.strict_json
            and Capability.structured_output not in task.model.capabilities
        ):
            warnings.append(
                "The model has no declared native structured-output capability; "
                "use parser validation and repair."
            )
        if not task.constraints.supplied_material and task.task_type in _NEEDS_MATERIAL:
            warnings.append(
                f"A {task.task_type.value} task works on something, and this request names a "
                "topic without supplying it. Paste the text into the request, or build a "
                "reusable template so the material arrives through {input}."
            )
        if task.constraints.retrieval_required and not any(
            item.technique.tools_required for item in selected
        ):
            warnings.append(
                "This task needs material the prompt does not contain, but no recommended "
                "technique can retrieve it. Give the model tool access (a tool_calling "
                "capability makes agents.react eligible), or paste the sources into the input."
            )

        return SelectionResult(
            recommendations=[item.recommendation for item in selected],
            rejected=sorted(rejected, key=lambda item: item.technique_id),
            warnings=warnings,
            task=task,
        )

    def _measurement(self, task: TaskProfile, technique: TechniqueSpec) -> MeasuredEvidence | None:
        if self.measurements is None:
            return None
        return self.measurements.lookup(
            technique_id=technique.id,
            task_type=task.task_type,
            provider=task.model.provider,
            model_id=task.model.model_id,
        )

    def _rejection_reasons(self, task: TaskProfile, technique: TechniqueSpec) -> list[str]:
        reasons: list[str] = []
        missing = technique.required_capabilities - task.model.capabilities
        if missing:
            reasons.append(
                "Missing model capabilities: " + ", ".join(sorted(item.value for item in missing))
            )
        if technique.tools_required and not task.constraints.tools_allowed:
            reasons.append("The technique requires tools, but tools are disabled.")
        if technique.requires_supplied_evidence and task.constraints.retrieval_required:
            reasons.append(
                "The technique answers only from evidence pasted into the prompt, but this "
                "task has to gather the material first."
            )
        elif technique.requires_supplied_evidence and not task.constraints.supplied_material:
            reasons.append(
                "The technique works on material carried by the prompt — quoting, filtering or "
                "translating it — and this request states a topic rather than supplying any."
            )
        if task.constraints.local_only and not task.model.local:
            reasons.append("The task requires local execution, but the model profile is remote.")
        if task.constraints.max_calls < technique.min_calls:
            reasons.append(
                f"The technique needs at least {technique.min_calls} calls; "
                f"max_calls is {task.constraints.max_calls}."
            )
        if task.task_type in technique.avoid_tasks:
            reasons.append(f"The technique is marked as unsuitable for {task.task_type.value}.")
        if technique.model_classes and task.model.model_class not in technique.model_classes:
            reasons.append(
                f"The technique is not recommended for the "
                f"{task.model.model_class.value} model class."
            )
        return reasons

    def _score(
        self,
        task: TaskProfile,
        technique: TechniqueSpec,
        measured: MeasuredEvidence | None,
        reference: _Reference,
        shape_fit: float = 0.5,
    ) -> Recommendation:
        priorities = task.priorities.normalized()

        if task.task_type in technique.strong_tasks:
            task_fit = 1.0
        elif task.task_type in technique.acceptable_tasks:
            task_fit = 0.72
        else:
            task_fit = 0.46

        model_fit = 1.0 if not technique.model_classes else 0.92
        if task.model.provider == "ollama" and "local-friendly" in technique.tags:
            model_fit = min(1.0, model_fit + 0.08)
        if task.model.model_class.value == "small" and "small-model-friendly" in technique.tags:
            model_fit = min(1.0, model_fit + 0.08)

        c = technique.characteristics
        axes = {
            "quality": c.quality,
            "reliability": c.reliability,
            "latency_efficiency": c.latency_efficiency,
            "token_efficiency": c.token_efficiency,
        }
        measured_axes: list[str] = []
        if measured is not None:
            axes["quality"] = measured.quality
            axes["reliability"] = measured.reliability
            measured_axes += ["quality", "reliability"]
            if reference.latency_seconds:
                axes["latency_efficiency"] = min(
                    1.0, reference.latency_seconds / max(measured.mean_latency_seconds, 1e-9)
                )
                measured_axes.append("latency_efficiency")
            if reference.total_tokens:
                axes["token_efficiency"] = min(
                    1.0, reference.total_tokens / max(measured.mean_total_tokens, 1e-9)
                )
                measured_axes.append("token_efficiency")

        priority_fit = (
            priorities.quality * axes["quality"]
            + priorities.reliability * axes["reliability"]
            + priorities.latency * axes["latency_efficiency"]
            + priorities.token_cost * axes["token_efficiency"]
        )

        if measured is not None:
            benchmark_prior, benchmark_reason = _measured_signal(task, measured)
            evidence_quality = max(
                EVIDENCE_SCORES[technique.evidence_level], _measured_evidence(measured)
            )
            evidence_source = "measured"
        else:
            benchmark_prior, benchmark_reason = self._benchmark_prior(task, technique)
            evidence_quality = EVIDENCE_SCORES[technique.evidence_level]
            evidence_source = "prior"

        penalty = (1 - c.simplicity) * 0.045
        # An extra model call is cheap on work that genuinely has steps and dear on
        # work that does not: this is what stops a two-stage recipe from winning a
        # one-line request on a hundredth of a point.
        penalty += max(0, technique.min_calls - 1) * _call_cost(task)
        if task.constraints.strict_json and not technique.strict_json_fit:
            penalty += 0.07
        if task.constraints.requires_validation and not technique.validation_fit:
            penalty += 0.035

        # A task that has to fetch its own material is not merely served better by a
        # tool loop: nothing else can finish it. That outranks the latency and token
        # cost the loop is otherwise penalised for.
        retrieval_fit = (
            1.0 if task.constraints.retrieval_required and technique.tools_required else 0.0
        )

        # Shape decides within a task type, never across it: a label-rules recipe
        # that happens to match "exact format" must not win an extraction task from
        # the recipes built for it. Multiplying gates the shape bonus behind fit.
        raw_score = (
            task_fit * (0.26 + 0.21 * shape_fit)
            + 0.10 * model_fit
            + 0.26 * priority_fit
            + 0.13 * benchmark_prior
            + 0.04 * evidence_quality
            + 0.12 * retrieval_fit
            - penalty
        )
        score = max(0.0, min(1.0, raw_score))

        reasons = [self._task_reason(task, technique)]
        covered = sorted(item.value for item in task.shape & technique.suits)
        if covered:
            reasons.append(f"Built for this request being {', '.join(covered).replace('_', ' ')}.")
        elif task.shape:
            reasons.append(
                "Declares no fit for what this request looks like ("
                + ", ".join(sorted(item.value.replace("_", " ") for item in task.shape))
                + ")."
            )
        source_label = (
            f"measured on {', '.join(measured_axes)}"
            if measured_axes
            else "declared characteristics"
        )
        reasons.append(
            f"Priority fit ({source_label}): quality {axes['quality']:.2f}, "
            f"reliability {axes['reliability']:.2f}, latency efficiency "
            f"{axes['latency_efficiency']:.2f}, token efficiency {axes['token_efficiency']:.2f}."
        )
        if task.constraints.strict_json and technique.strict_json_fit:
            reasons.append("Designed for strict structured output.")
        if task.constraints.requires_validation and technique.validation_fit:
            reasons.append("Includes an explicit validation path.")
        if retrieval_fit:
            reasons.append("Can fetch the material this task is missing, through tool calls.")
        reasons.append(benchmark_reason)
        reasons.append(
            f"Executes as {technique.execution.strategy} ({technique.min_calls} call minimum)."
        )

        return Recommendation(
            technique_id=technique.id,
            title=technique.title,
            family=technique.family,
            score=round(score, 4),
            confidence=0.0,
            reasons=reasons,
            breakdown=ScoreBreakdown(
                task_fit=round(task_fit, 4),
                shape_fit=round(shape_fit, 4),
                model_fit=round(model_fit, 4),
                priority_fit=round(priority_fit, 4),
                benchmark_prior=round(benchmark_prior, 4),
                evidence_quality=round(evidence_quality, 4),
                penalties=round(penalty, 4),
                retrieval_fit=retrieval_fit,
            ),
            evidence_source=evidence_source,
            measured=measured,
        )

    @staticmethod
    def _task_reason(task: TaskProfile, technique: TechniqueSpec) -> str:
        if task.task_type in technique.strong_tasks:
            return f"Strong declared fit for {task.task_type.value}."
        if task.task_type in technique.acceptable_tasks:
            return f"Compatible with {task.task_type.value}."
        return f"General-purpose fallback for {task.task_type.value}."

    @staticmethod
    def _benchmark_prior(task: TaskProfile, technique: TechniqueSpec) -> tuple[float, str]:
        keys = [
            f"task:{task.task_type.value}",
            f"provider:{task.model.provider}",
            f"class:{task.model.model_class.value}",
            "default",
        ]
        weighted: list[tuple[float, float, str]] = []
        weights = [0.45, 0.25, 0.20, 0.10]
        for key, weight in zip(keys, weights, strict=True):
            if key in technique.benchmark_priors:
                weighted.append((technique.benchmark_priors[key], weight, key))
        if not weighted:
            return 0.5, "No matching benchmark prior; using a neutral prior."
        total_weight = sum(item[1] for item in weighted)
        score = sum(value * weight for value, weight, _ in weighted) / total_weight
        matched = ", ".join(key for _, _, key in weighted)
        return score, f"Unmeasured prior {score:.2f} from: {matched}."

    @staticmethod
    def _diverse_top(candidates: list[_Scored], limit: int) -> list[_Scored]:
        selected: list[_Scored] = []
        used_families: set[str] = set()
        for candidate in candidates:
            if candidate.technique.family not in used_families:
                selected.append(candidate)
                used_families.add(candidate.technique.family)
            if len(selected) == limit:
                return selected
        for candidate in candidates:
            if candidate not in selected:
                selected.append(candidate)
            if len(selected) == limit:
                break
        return selected

    @staticmethod
    def _apply_confidence(selected: list[_Scored], all_candidates: list[_Scored]) -> list[_Scored]:
        if not selected:
            return selected
        top_score = all_candidates[0].recommendation.score
        second_score = all_candidates[1].recommendation.score if len(all_candidates) > 1 else 0.0
        margin = max(0.0, top_score - second_score)
        updated: list[_Scored] = []
        for index, item in enumerate(selected):
            evidence = item.recommendation.breakdown.evidence_quality
            benchmark = item.recommendation.breakdown.benchmark_prior
            rank_factor = max(0.65, 1 - index * 0.12)
            confidence = min(
                0.98, (0.48 * evidence + 0.37 * benchmark + 0.15 * min(1, margin * 8)) * rank_factor
            )
            recommendation = item.recommendation.model_copy(
                update={"confidence": round(confidence, 4)}
            )
            updated.append(_Scored(item.technique, recommendation))
        return updated


def _measured_signal(task: TaskProfile, measured: MeasuredEvidence) -> tuple[float, str]:
    """Collapse measured quality and reliability using what the task cares about."""
    priorities = task.priorities.normalized()
    weight = priorities.quality + priorities.reliability
    if weight <= 0:
        signal = (measured.quality + measured.reliability) / 2
    else:
        signal = (
            priorities.quality * measured.quality + priorities.reliability * measured.reliability
        ) / weight
    runs = measured.examples * measured.repeats
    return round(signal, 4), (
        f"Measured {signal:.2f} on {measured.model_id}: quality {measured.quality:.2f}, "
        f"reliability {measured.reliability:.2f}, {measured.mean_latency_seconds:.2f}s, "
        f"{measured.mean_total_tokens:.0f} tokens per example "
        f"({runs} runs on {measured.dataset}, {measured.recorded_at[:10]})."
    )


def _measured_evidence(measured: MeasuredEvidence) -> float:
    runs = measured.examples * measured.repeats
    if runs >= 20:
        return 0.95
    if runs >= 5:
        return 0.82
    return 0.70


def _reference_costs(measurements) -> _Reference:
    latencies = [
        item.mean_latency_seconds for item in measurements if item and item.mean_latency_seconds > 0
    ]
    tokens = [
        item.mean_total_tokens for item in measurements if item and item.mean_total_tokens > 0
    ]
    return _Reference(
        latency_seconds=min(latencies) if latencies else None,
        total_tokens=min(tokens) if tokens else None,
    )
