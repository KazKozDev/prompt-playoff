"""Real benchmarking: run the compiled prompt against a real model and measure.

Nothing in this module estimates. Quality, reliability, latency and token cost
are computed from actual provider calls on the prompt the compiler produced for
the technique the user picked.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

from pydantic import BaseModel, Field

from prompt_playoff.compiler import PromptCompiler
from prompt_playoff.domain import (
    ExecutionTrace,
    Exemplar,
    MeasuredEvidence,
    TaskProfile,
    TechniqueSpec,
)
from prompt_playoff.graders import (
    QUALITY_PREFERENCE,
    RELIABILITY_GRADERS,
    GradeContext,
    default_graders,
    run_graders,
    validate_schema,
)
from prompt_playoff.providers import ModelProvider, ProviderError
from prompt_playoff.strategies import canonical, get_strategy


class BenchmarkExample(BaseModel):
    id: str
    input: str
    expected: Any | None = None
    response_schema: dict[str, Any] | None = None
    graders: list[str] = Field(default_factory=list)
    grader_options: dict[str, Any] = Field(default_factory=dict)
    variables: dict[str, str] = Field(default_factory=dict)
    exemplars: list[Exemplar] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class ExampleRun(BaseModel):
    example_id: str
    repeat: int
    output: str
    grades: dict[str, float]
    latency_seconds: float
    prompt_tokens: int
    completion_tokens: int
    calls: int
    cost_usd: float | None = None
    aggregation: dict[str, Any] = Field(default_factory=dict)
    schema_errors: list[str] = Field(default_factory=list)
    error: str | None = None

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class Scorecard(BaseModel):
    """Every field here is measured, not declared."""

    quality: float
    reliability: float
    contract_pass_rate: float
    stability: float
    mean_latency_seconds: float
    p95_latency_seconds: float
    mean_total_tokens: float
    mean_prompt_tokens: float
    mean_completion_tokens: float
    mean_calls: float
    mean_cost_usd: float | None = None
    total_cost_usd: float | None = None
    grades: dict[str, float] = Field(default_factory=dict)
    quality_grader: str | None = None
    failures: int = 0
    runs: int = 0


class BenchmarkReport(BaseModel):
    technique_id: str
    technique_title: str
    strategy: str
    provider: str
    model_id: str
    task_type: str
    dataset: str
    examples: int
    repeats: int
    started_at: str
    finished_at: str
    scorecard: Scorecard
    declared: dict[str, float] = Field(default_factory=dict)
    prior: float | None = None
    delta: dict[str, float] = Field(default_factory=dict)
    runs: list[ExampleRun] = Field(default_factory=list)
    prompt_preview: dict[str, Any] = Field(default_factory=dict)

    def to_evidence(self) -> MeasuredEvidence:
        return MeasuredEvidence(
            technique_id=self.technique_id,
            task_type=self.task_type,  # type: ignore[arg-type]
            provider=self.provider,
            model_id=self.model_id,
            quality=self.scorecard.quality,
            reliability=self.scorecard.reliability,
            mean_latency_seconds=self.scorecard.mean_latency_seconds,
            mean_total_tokens=self.scorecard.mean_total_tokens,
            examples=self.examples,
            repeats=self.repeats,
            dataset=self.dataset,
            recorded_at=self.finished_at,
        )


class ComparisonEntry(BaseModel):
    technique_id: str
    technique_title: str
    strategy: str
    scorecard: Scorecard
    latency_efficiency: float
    token_efficiency: float
    weighted_score: float
    declared_score: float | None = None


class ComparisonReport(BaseModel):
    dataset: str
    model_id: str
    provider: str
    task_type: str
    repeats: int
    entries: list[ComparisonEntry]
    winner: str
    priorities: dict[str, float]
    note: str = (
        "latency_efficiency and token_efficiency are relative to the best measured "
        "technique in this comparison; weighted_score applies the task priorities to "
        "measured numbers only."
    )


ProgressCallback = Callable[[dict[str, Any]], None]


class BenchmarkRunner:
    def __init__(self, provider: ModelProvider, compiler: PromptCompiler | None = None) -> None:
        self.provider = provider
        self.compiler = compiler or PromptCompiler()

    async def run(
        self,
        dataset: list[BenchmarkExample],
        task: TaskProfile,
        technique: TechniqueSpec,
        repeats: int = 1,
        timeout_seconds: float = 120,
        dataset_name: str = "inline",
        progress: ProgressCallback | None = None,
    ) -> BenchmarkReport:
        if not dataset:
            raise ValueError("Benchmark dataset is empty")
        strategy = get_strategy(technique.execution.strategy)
        started = _now()
        runs: list[ExampleRun] = []
        preview: dict[str, Any] = {}
        total = len(dataset) * repeats
        done = 0

        for example in dataset:
            program = self.compiler.compile(
                task=task,
                technique=technique,
                user_input=example.input,
                response_schema=example.response_schema,
                variables=example.variables,
                exemplars=example.exemplars,
            )
            if not preview:
                preview = {
                    "example_id": example.id,
                    "expected_calls": program.expected_calls,
                    "stages": [
                        {
                            "stage": stage.stage,
                            "system": stage.messages[0].content,
                            "user": stage.messages[1].content,
                        }
                        for stage in program.stages
                    ],
                    "response_schema": program.response_schema,
                    "notes": program.notes,
                }

            # Dataset graders win; otherwise infer from the data and always add the
            # technique's own validators, which return None when inapplicable.
            grader_names = example.graders or default_graders(
                example.expected,
                example.response_schema,
                task.constraints.strict_json,
            )
            grader_names = list(dict.fromkeys([*grader_names, *technique.recipe.validators]))

            for repeat in range(repeats):
                seeded = _with_seed(program, repeat)
                try:
                    trace = await strategy.execute(seeded, task, self.provider, timeout_seconds)
                    run = self._grade(example, trace, grader_names, repeat, task)
                except ProviderError as exc:
                    run = ExampleRun(
                        example_id=example.id,
                        repeat=repeat,
                        output="",
                        grades={},
                        latency_seconds=0.0,
                        prompt_tokens=0,
                        completion_tokens=0,
                        calls=0,
                        error=str(exc),
                    )
                runs.append(run)
                done += 1
                if progress:
                    progress(
                        {
                            "completed": done,
                            "total": total,
                            "example_id": example.id,
                            "repeat": repeat,
                            "technique_id": technique.id,
                        }
                    )

        finished = _now()
        scorecard = build_scorecard(runs, repeats)
        declared = {
            "quality": technique.characteristics.quality,
            "reliability": technique.characteristics.reliability,
        }
        return BenchmarkReport(
            technique_id=technique.id,
            technique_title=technique.title,
            strategy=technique.execution.strategy,
            provider=task.model.provider,
            model_id=task.model.model_id,
            task_type=task.task_type.value,
            dataset=dataset_name,
            examples=len(dataset),
            repeats=repeats,
            started_at=started,
            finished_at=finished,
            scorecard=scorecard,
            declared=declared,
            prior=technique.benchmark_priors.get(f"task:{task.task_type.value}")
            or technique.benchmark_priors.get("default"),
            delta={
                "quality": round(scorecard.quality - declared["quality"], 4),
                "reliability": round(scorecard.reliability - declared["reliability"], 4),
            },
            runs=runs,
            prompt_preview=preview,
        )

    def _grade(
        self,
        example: BenchmarkExample,
        trace: ExecutionTrace,
        grader_names: list[str],
        repeat: int,
        task: TaskProfile,
    ) -> ExampleRun:
        ctx = GradeContext(
            output=trace.output,
            expected=example.expected,
            response_schema=example.response_schema,
            trace=trace,
            options=example.grader_options,
        )
        grades = run_graders(grader_names, ctx)
        schema_errors: list[str] = []
        if example.response_schema is not None:
            schema_errors = validate_schema(ctx.parsed, example.response_schema)[:5]
        return ExampleRun(
            example_id=example.id,
            repeat=repeat,
            output=trace.output,
            grades=grades,
            latency_seconds=trace.latency_seconds,
            prompt_tokens=trace.prompt_tokens,
            completion_tokens=trace.completion_tokens,
            calls=len(trace.calls),
            cost_usd=_cost_usd(
                trace.prompt_tokens,
                trace.completion_tokens,
                task.model.input_cost_per_million_usd,
                task.model.output_cost_per_million_usd,
            ),
            aggregation=trace.aggregation,
            schema_errors=schema_errors,
        )


def build_scorecard(runs: list[ExampleRun], repeats: int) -> Scorecard:
    if not runs:
        raise ValueError("No runs to score")

    grade_names = sorted({name for run in runs for name in run.grades})
    grades = {
        name: round(mean([run.grades[name] for run in runs if name in run.grades]), 4)
        for name in grade_names
    }

    quality_grader = next((name for name in QUALITY_PREFERENCE if name in grades), None)
    quality = grades.get(quality_grader, 0.0) if quality_grader else 0.0

    contract_names = [name for name in grade_names if name in RELIABILITY_GRADERS]
    contract_values = [
        run.grades[name] for run in runs for name in contract_names if name in run.grades
    ]
    contract_pass = (
        round(mean(contract_values), 4)
        if contract_values
        else (1.0 if not any(run.error for run in runs) else 0.0)
    )

    stability = _stability(runs, repeats)
    reliability = round(contract_pass * stability, 4)

    latencies = sorted(run.latency_seconds for run in runs if run.error is None)
    p95 = (
        latencies[min(len(latencies) - 1, int(round(0.95 * (len(latencies) - 1))))]
        if latencies
        else 0.0
    )

    costs = [run.cost_usd for run in runs if run.cost_usd is not None]
    return Scorecard(
        quality=round(quality, 4),
        reliability=reliability,
        contract_pass_rate=contract_pass,
        stability=stability,
        mean_latency_seconds=round(mean([run.latency_seconds for run in runs]), 4),
        p95_latency_seconds=round(p95, 4),
        mean_total_tokens=round(mean([run.total_tokens for run in runs]), 2),
        mean_prompt_tokens=round(mean([run.prompt_tokens for run in runs]), 2),
        mean_completion_tokens=round(mean([run.completion_tokens for run in runs]), 2),
        mean_calls=round(mean([run.calls for run in runs]), 2),
        mean_cost_usd=round(mean(costs), 8) if len(costs) == len(runs) else None,
        total_cost_usd=round(sum(costs), 8) if len(costs) == len(runs) else None,
        grades=grades,
        quality_grader=quality_grader,
        failures=sum(1 for run in runs if run.error),
        runs=len(runs),
    )


def _cost_usd(
    prompt_tokens: int,
    completion_tokens: int,
    input_rate: float | None,
    output_rate: float | None,
) -> float | None:
    if input_rate is None or output_rate is None:
        return None
    return round((prompt_tokens * input_rate + completion_tokens * output_rate) / 1_000_000, 8)


def _stability(runs: list[ExampleRun], repeats: int) -> float:
    """Fraction of repeats that produced the modal answer, averaged over examples."""
    if repeats < 2:
        return 1.0
    by_example: dict[str, list[str]] = {}
    for run in runs:
        by_example.setdefault(run.example_id, []).append(canonical(run.output))
    ratios = []
    for outputs in by_example.values():
        if not outputs:
            continue
        modal = Counter(outputs).most_common(1)[0][1]
        ratios.append(modal / len(outputs))
    return round(mean(ratios), 4) if ratios else 1.0


async def compare_techniques(
    dataset: list[BenchmarkExample],
    task: TaskProfile,
    techniques: list[TechniqueSpec],
    provider: ModelProvider,
    repeats: int = 1,
    timeout_seconds: float = 120,
    dataset_name: str = "inline",
    progress: ProgressCallback | None = None,
) -> tuple[ComparisonReport, list[BenchmarkReport]]:
    """Run several techniques on the same data and rank them on measured numbers."""
    runner = BenchmarkRunner(provider)
    reports: list[BenchmarkReport] = []
    for technique in techniques:
        reports.append(
            await runner.run(
                dataset=dataset,
                task=task,
                technique=technique,
                repeats=repeats,
                timeout_seconds=timeout_seconds,
                dataset_name=dataset_name,
                progress=progress,
            )
        )

    best_latency = min((r.scorecard.mean_latency_seconds for r in reports), default=0.0) or 1e-9
    best_tokens = min((r.scorecard.mean_total_tokens for r in reports), default=0.0) or 1e-9
    priorities = task.priorities.normalized()

    entries: list[ComparisonEntry] = []
    for report in reports:
        latency_efficiency = round(
            best_latency / max(report.scorecard.mean_latency_seconds, 1e-9), 4
        )
        token_efficiency = round(best_tokens / max(report.scorecard.mean_total_tokens, 1e-9), 4)
        weighted = (
            priorities.quality * report.scorecard.quality
            + priorities.reliability * report.scorecard.reliability
            + priorities.latency * latency_efficiency
            + priorities.token_cost * token_efficiency
        )
        entries.append(
            ComparisonEntry(
                technique_id=report.technique_id,
                technique_title=report.technique_title,
                strategy=report.strategy,
                scorecard=report.scorecard,
                latency_efficiency=min(1.0, latency_efficiency),
                token_efficiency=min(1.0, token_efficiency),
                weighted_score=round(weighted, 4),
            )
        )

    entries.sort(key=lambda item: item.weighted_score, reverse=True)
    comparison = ComparisonReport(
        dataset=dataset_name,
        model_id=task.model.model_id,
        provider=task.model.provider,
        task_type=task.task_type.value,
        repeats=repeats,
        entries=entries,
        winner=entries[0].technique_id if entries else "",
        priorities=priorities.model_dump(),
    )
    return comparison, reports


def _with_seed(program, repeat: int):
    seeded = program.model_copy(deep=True)
    for index, stage in enumerate(seeded.stages):
        stage.generation_options = {
            **stage.generation_options,
            "seed": repeat * 1000 + index,
        }
    return seeded


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def load_jsonl(path: Path) -> list[BenchmarkExample]:
    return load_jsonl_text(path.read_text(encoding="utf-8"))


def load_jsonl_text(text: str) -> list[BenchmarkExample]:
    """Validate JSONL text and preserve the first failing physical line number."""
    examples: list[BenchmarkExample] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            examples.append(BenchmarkExample.model_validate_json(line))
        except Exception as exc:
            raise ValueError(f"Invalid JSONL at line {line_number}: {exc}") from exc
    return examples


def run_sync(coro):
    return asyncio.run(coro)
