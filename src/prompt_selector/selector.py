from __future__ import annotations

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

        candidates = [
            _Scored(technique, self._score(task, technique, measured.get(technique.id), reference))
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
        penalty += max(0, technique.min_calls - 1) * 0.018
        if task.constraints.strict_json and not technique.strict_json_fit:
            penalty += 0.07
        if task.constraints.requires_validation and not technique.validation_fit:
            penalty += 0.035

        raw_score = (
            0.30 * task_fit
            + 0.15 * model_fit
            + 0.35 * priority_fit
            + 0.15 * benchmark_prior
            + 0.05 * evidence_quality
            - penalty
        )
        score = max(0.0, min(1.0, raw_score))

        reasons = [self._task_reason(task, technique)]
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
                model_fit=round(model_fit, 4),
                priority_fit=round(priority_fit, 4),
                benchmark_prior=round(benchmark_prior, 4),
                evidence_quality=round(evidence_quality, 4),
                penalties=round(penalty, 4),
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
