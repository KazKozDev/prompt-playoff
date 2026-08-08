"""DSPy as an alternative search algorithm for the optimizer.

The division of labour matters here. DSPy contributes the *search*: MIPROv2's
Bayesian joint proposal over instructions and demonstrations, GEPA's reflective
Pareto evolution, BootstrapFewShot's demo selection. It does **not** get to own
the prompt or the score.

Every candidate DSPy proposes is rendered by ``PromptCompiler``, executed by the
technique's own strategy, and graded by :mod:`prompt_selector.graders`. So a
DSPy run and a native run optimize the same artefact against the same numbers,
and the winner comes back as a plain ``TechniqueOverlay`` that the rest of the
project already knows how to compile, benchmark and export.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any, Literal, cast

from prompt_selector.compiler import PromptCompiler
from prompt_selector.domain import Exemplar, ModelProfile, TaskProfile, TechniqueSpec
from prompt_selector.evals import BenchmarkExample, BenchmarkRunner
from prompt_selector.graders import (
    QUALITY_PREFERENCE,
    RELIABILITY_GRADERS,
    GradeContext,
    run_graders,
)
from prompt_selector.integrations import require
from prompt_selector.optimizer import (
    MUTABLE_BLOCKS,
    Candidate,
    OptimizationResult,
    OptimizationRound,
    ProgressCallback,
    TechniqueOverlay,
    _failure_digest,
    _rescore,
    _split,
    export_technique,
    pareto_front,
)
from prompt_selector.providers import ModelProvider, ProviderError
from prompt_selector.strategies import get_strategy

OPTIMIZERS = ("mipro", "gepa", "bootstrap")
AutoLevel = Literal["light", "medium", "heavy"]


def litellm_model(model: ModelProfile) -> tuple[str, dict[str, Any]]:
    """Map a model profile onto the litellm identifier DSPy expects."""
    if model.provider == "ollama":
        return f"ollama_chat/{model.model_id}", {
            "api_base": model.base_url or "http://127.0.0.1:11434"
        }
    kwargs: dict[str, Any] = {}
    if model.base_url:
        kwargs["api_base"] = model.base_url
    return f"openai/{model.model_id}", kwargs


def mutable_block(technique: TechniqueSpec) -> str | None:
    for block in technique.recipe.blocks:
        if block.name in MUTABLE_BLOCKS:
            return block.name
    return None


def example_score(
    example: BenchmarkExample,
    output: str,
    trace,
    technique: TechniqueSpec,
    task: TaskProfile,
    token_reference: float | None = None,
    tokens: int = 0,
) -> tuple[float, dict[str, float]]:
    """One scalar per example, built from the same graders the benchmark uses."""
    from prompt_selector.graders import default_graders

    names = example.graders or default_graders(
        example.expected, example.response_schema, task.constraints.strict_json
    )
    names = list(dict.fromkeys([*names, *technique.recipe.validators]))
    grades = run_graders(
        names,
        GradeContext(
            output=output,
            expected=example.expected,
            response_schema=example.response_schema,
            trace=trace,
            options=example.grader_options,
        ),
    )
    quality_key = next((name for name in QUALITY_PREFERENCE if name in grades), None)
    quality = grades.get(quality_key, 0.0) if quality_key else 0.0
    contract = [grades[name] for name in grades if name in RELIABILITY_GRADERS]
    reliability = sum(contract) / len(contract) if contract else 1.0

    priorities = task.priorities.normalized()
    weight = priorities.quality + priorities.reliability
    score = (
        (priorities.quality * quality + priorities.reliability * reliability) / weight
        if weight
        else (quality + reliability) / 2
    )

    # Token cost is part of what the user asked to optimize, so it participates
    # here rather than only in the final report.
    if token_reference and tokens and priorities.token_cost:
        efficiency = min(1.0, token_reference / max(tokens, 1))
        score = score * (1 - priorities.token_cost) + efficiency * priorities.token_cost
    return round(score, 4), grades


class _Runner:
    """Executes one candidate through the real pipeline, synchronously for DSPy."""

    def __init__(
        self,
        task: TaskProfile,
        technique: TechniqueSpec,
        provider: ModelProvider,
        compiler: PromptCompiler,
        timeout_seconds: float,
    ) -> None:
        self.task = task
        self.technique = technique
        self.provider = provider
        self.compiler = compiler
        self.timeout_seconds = timeout_seconds
        self.block = mutable_block(technique)
        self.calls = 0

    def __call__(
        self, example: BenchmarkExample, instructions: str, demos: list[Exemplar]
    ) -> tuple[str, Any, int]:
        overlay = TechniqueOverlay(
            block_bodies={self.block: instructions.strip() + "\n"} if self.block else {},
            exemplars=demos,
        )
        patched = overlay.apply(self.technique)
        program = self.compiler.compile(
            task=self.task,
            technique=patched,
            user_input=example.input,
            response_schema=example.response_schema,
            variables=example.variables,
            exemplars=[*example.exemplars, *demos],
        )
        strategy = get_strategy(program.strategy)
        try:
            trace = asyncio.run(
                strategy.execute(program, self.task, self.provider, self.timeout_seconds)
            )
        except ProviderError:
            return "", None, 0
        self.calls += len(trace.calls)
        return trace.output, trace, trace.total_tokens


async def optimize_with_dspy(
    task: TaskProfile,
    technique: TechniqueSpec,
    dataset: list[BenchmarkExample],
    provider: ModelProvider,
    optimizer: str = "mipro",
    auto: AutoLevel = "light",
    max_metric_calls: int | None = None,
    repeats: int = 1,
    validation_ratio: float = 0.34,
    timeout_seconds: float = 120,
    dataset_name: str = "inline",
    proposer_model: ModelProfile | None = None,
    compiler: PromptCompiler | None = None,
    progress: ProgressCallback | None = None,
) -> OptimizationResult:
    require("dspy", "dspy")
    if optimizer not in OPTIMIZERS:
        raise ValueError(f"Unknown DSPy optimizer {optimizer!r}. Known: {', '.join(OPTIMIZERS)}")
    if optimizer == "mipro":
        # MIPROv2 imports optuna only at its third step, which is after it has
        # already spent model calls. Fail before the run, not during it.
        require("optuna", "dspy")
    if len(dataset) < 2:
        raise ValueError("Optimization needs at least two examples to split")

    compiler = compiler or PromptCompiler()
    started = time.perf_counter()
    train, validation = _split(dataset, validation_ratio)
    block = mutable_block(technique)
    if block is None:
        raise ValueError(
            f"{technique.id} has no instruction block to optimize "
            f"(expected one of: {', '.join(MUTABLE_BLOCKS)})"
        )
    baseline_instructions = next(
        item.body for item in technique.recipe.blocks if item.name == block
    )

    runner = _Runner(task, technique, provider, compiler, timeout_seconds)
    outcome = await asyncio.to_thread(
        _compile_sync,
        optimizer,
        auto,
        max_metric_calls,
        runner,
        train,
        validation,
        task,
        technique,
        baseline_instructions,
        proposer_model or task.model,
        progress,
    )

    winner_overlay = TechniqueOverlay(
        block_bodies={block: outcome["instructions"].strip() + "\n"},
        exemplars=outcome["demos"],
    )
    notes = list(outcome["notes"])
    if outcome["demos"] and not _renders_exemplars(technique):
        notes.append(
            f"{len(outcome['demos'])} demonstration(s) were bootstrapped, but {technique.id} "
            "declares no block with `when: has_exemplars`, so they never reach the model. "
            "Optimize a technique with an example block to benefit from demo search."
        )
    baseline = Candidate(id="baseline", technique_id=technique.id, origin="baseline")
    winner = Candidate(
        id=f"dspy-{optimizer}",
        technique_id=technique.id,
        origin=f"dspy:{optimizer}",
        overlay=winner_overlay,
    )

    # Held-out verification runs through our own benchmark, not DSPy's evaluator.
    bench = BenchmarkRunner(provider, compiler)
    baseline_report = await bench.run(
        dataset=validation,
        task=task,
        technique=technique,
        repeats=repeats,
        timeout_seconds=timeout_seconds,
        dataset_name=dataset_name,
    )
    winner_report = await bench.run(
        dataset=_with_demos(validation, outcome["demos"]),
        task=task,
        technique=winner_overlay.apply(technique),
        repeats=repeats,
        timeout_seconds=timeout_seconds,
        dataset_name=dataset_name,
    )
    baseline.train = baseline_report.scorecard
    winner.train = winner_report.scorecard
    # DSPy reports its own aggregate on its own scale (often a percentage). Mixing
    # that into the same column as the native weighted score makes the search
    # history unreadable, so both arms are rescored here with our own function.
    _rescore([baseline, winner], task.priorities.normalized())

    preview = compiler.compile(
        task=task,
        technique=winner_overlay.apply(technique),
        user_input=dataset[0].input,
        response_schema=dataset[0].response_schema,
        variables=dataset[0].variables,
        exemplars=[*dataset[0].exemplars, *outcome["demos"]],
    )

    base_card, best_card = baseline_report.scorecard, winner_report.scorecard
    return OptimizationResult(
        task_type=task.task_type.value,
        model_id=task.model.model_id,
        dataset=dataset_name,
        train_size=len(train),
        validation_size=len(validation),
        rounds=[
            OptimizationRound(
                round=1,
                evaluated=[baseline, winner],
                best_id=winner.id,
                best_score=winner.score or 0.0,
            )
        ],
        baseline_id="baseline",
        winner=winner,
        baseline_validation=base_card,
        winner_validation=best_card,
        improvement={
            "quality": round(best_card.quality - base_card.quality, 4),
            "reliability": round(best_card.reliability - base_card.reliability, 4),
            "mean_total_tokens": round(
                best_card.mean_total_tokens - base_card.mean_total_tokens, 2
            ),
            "mean_latency_seconds": round(
                best_card.mean_latency_seconds - base_card.mean_latency_seconds, 4
            ),
        },
        pareto_front=pareto_front([baseline, winner]),
        compiled_prompt={
            "strategy": preview.strategy,
            "expected_calls": preview.expected_calls,
            "stages": [
                {
                    "stage": stage.stage,
                    "system": stage.messages[0].content,
                    "user": stage.messages[1].content,
                }
                for stage in preview.stages
            ],
        },
        exported_technique=export_technique(winner_overlay.apply(technique), winner),
        total_calls=runner.calls,
        elapsed_seconds=round(time.perf_counter() - started, 2),
        priorities=task.priorities.normalized().model_dump(),
        backend=f"dspy:{optimizer}",
        notes=notes,
    )


def _renders_exemplars(technique: TechniqueSpec) -> bool:
    from prompt_selector.domain import BlockCondition

    return any(block.when is BlockCondition.has_exemplars for block in technique.recipe.blocks)


def _with_demos(dataset: list[BenchmarkExample], demos: list[Exemplar]) -> list[BenchmarkExample]:
    if not demos:
        return dataset
    return [item.model_copy(update={"exemplars": [*item.exemplars, *demos]}) for item in dataset]


def _compile_sync(
    optimizer: str,
    auto: AutoLevel,
    max_metric_calls: int | None,
    runner: _Runner,
    train: list[BenchmarkExample],
    validation: list[BenchmarkExample],
    task: TaskProfile,
    technique: TechniqueSpec,
    baseline_instructions: str,
    proposer_model: ModelProfile,
    progress: ProgressCallback | None,
) -> dict[str, Any]:
    """Everything that touches DSPy runs here, on a worker thread."""
    import dspy

    by_id = {item.id: item for item in [*train, *validation]}
    token_reference: dict[str, float] = {}

    signature = dspy.make_signature(
        "task_input -> output",
        baseline_instructions.strip(),
        signature_name="PromptSelectorTask",
    )

    class Program(dspy.Module):
        def __init__(self) -> None:
            super().__init__()
            self.predict = dspy.Predict(signature)

        def forward(self, task_input: str, example_id: str = "", **_: Any):
            example = by_id.get(example_id)
            if example is None:
                return dspy.Prediction(output="", tokens=0)
            demos = _demos_to_exemplars(self.predict.demos)
            output, trace, tokens = runner(
                example, cast(Any, self.predict).signature.instructions, demos
            )
            prediction = dspy.Prediction(output=output, tokens=tokens, exec_trace=trace)
            # Mirror dspy.Predict so bootstrapping can still collect demos.
            recorded = dspy.settings.trace
            if recorded is not None and dspy.settings.max_trace_size > 0:
                if len(recorded) >= dspy.settings.max_trace_size:
                    recorded.pop(0)
                recorded.append((self.predict, {"task_input": task_input}, prediction))
            if progress:
                progress({"phase": "dspy_eval", "example_id": example_id, "backend": optimizer})
            return prediction

    def to_example(item: BenchmarkExample):
        return dspy.Example(task_input=item.input, example_id=item.id).with_inputs(
            "task_input", "example_id"
        )

    trainset = [to_example(item) for item in train]
    valset = [to_example(item) for item in validation]

    def score_of(gold, pred) -> tuple[float, dict[str, float]]:
        example = by_id.get(getattr(gold, "example_id", ""))
        if example is None:
            return 0.0, {}
        return example_score(
            example=example,
            output=getattr(pred, "output", "") or "",
            trace=getattr(pred, "exec_trace", None),
            technique=technique,
            task=task,
            token_reference=token_reference.get("baseline"),
            tokens=int(getattr(pred, "tokens", 0) or 0),
        )

    def metric(gold, pred, trace=None, *args, **kwargs) -> float:
        return score_of(gold, pred)[0]

    program = Program()

    # A baseline pass gives the token reference the metric needs, and the score
    # the report compares against.
    baseline_scores: list[float] = []
    baseline_tokens: list[int] = []
    for item in train:
        prediction = program(task_input=item.input, example_id=item.id)
        baseline_tokens.append(int(getattr(prediction, "tokens", 0) or 0))
        baseline_scores.append(score_of(to_example(item), prediction)[0])
    if baseline_tokens and any(baseline_tokens):
        token_reference["baseline"] = sum(baseline_tokens) / len(baseline_tokens)
    baseline_score = (
        round(sum(baseline_scores) / len(baseline_scores), 4) if baseline_scores else 0.0
    )

    proposer_id, proposer_kwargs = litellm_model(proposer_model)
    proposer = dspy.LM(
        proposer_id, temperature=1.0, max_tokens=2048, cache=False, **proposer_kwargs
    )
    notes: list[str] = []

    with dspy.context(lm=proposer, adapter=dspy.ChatAdapter()):
        if optimizer == "bootstrap":
            teleprompter = dspy.BootstrapFewShot(
                metric=metric, max_bootstrapped_demos=3, max_labeled_demos=3, max_rounds=1
            )
            optimized = teleprompter.compile(program, trainset=trainset)
            notes.append(
                "BootstrapFewShot selects demonstrations only; instructions are unchanged."
            )
        elif optimizer == "mipro":
            teleprompter = dspy.MIPROv2(
                metric=metric,
                prompt_model=proposer,
                task_model=proposer,
                auto=auto,
                num_threads=1,
                max_bootstrapped_demos=2,
                max_labeled_demos=2,
            )
            optimized = teleprompter.compile(
                program,
                trainset=trainset,
                valset=valset or None,
                requires_permission_to_run=False,
                minibatch=False,
            )
            notes.append(
                f"MIPROv2 ({auto}) proposed instructions and demonstrations jointly; "
                "every candidate was scored on real runs of the compiled prompt."
            )
        else:
            from dspy.teleprompt.gepa.gepa import ScoreWithFeedback

            def gepa_metric(
                gold, pred, trace=None, pred_name=None, pred_trace=None, program_trace=None
            ):
                score, grades = score_of(gold, pred)
                example = by_id.get(getattr(gold, "example_id", ""))
                feedback = _feedback(example, getattr(pred, "output", ""), grades, score)
                return ScoreWithFeedback(score=score, feedback=feedback)

            teleprompter = dspy.GEPA(
                metric=gepa_metric,
                reflection_lm=proposer,
                auto=None if max_metric_calls else auto,
                max_metric_calls=max_metric_calls,
                candidate_selection_strategy="pareto",
                num_threads=1,
                track_stats=True,
            )
            optimized = teleprompter.compile(program, trainset=trainset, valset=valset or trainset)
            notes.append(
                "GEPA evolved instructions from textual feedback on real failures, "
                "keeping a Pareto front of candidates."
            )

    predictor = getattr(optimized, "predict", None) or program.predict
    best_score = _best_score(optimized, baseline_score)
    return {
        "instructions": cast(Any, predictor).signature.instructions,
        "demos": _demos_to_exemplars(getattr(predictor, "demos", [])),
        "baseline_score": baseline_score,
        "best_score": best_score,
        "notes": notes,
    }


def _best_score(optimized: Any, fallback: float) -> float:
    for attribute in ("score", "best_score"):
        value = getattr(optimized, attribute, None)
        if isinstance(value, (int, float)):
            return round(float(value), 4)
    detailed = getattr(optimized, "detailed_results", None)
    best = getattr(detailed, "best_score", None) if detailed is not None else None
    if isinstance(best, (int, float)):
        return round(float(best), 4)
    return fallback


def _demos_to_exemplars(demos: list[Any]) -> list[Exemplar]:
    exemplars: list[Exemplar] = []
    for demo in demos or []:
        data = demo if isinstance(demo, dict) else getattr(demo, "toDict", lambda: {})()
        source = data.get("task_input")
        result = data.get("output")
        if source and result:
            exemplars.append(Exemplar(input=str(source), output=str(result)))
    return exemplars


def _feedback(
    example: BenchmarkExample | None, output: str, grades: dict[str, float], score: float
) -> str:
    """Concrete, checkable feedback. GEPA's proposals are only as good as this."""
    if example is None:
        return "No example context available."
    lines = [f"Score {score:.2f}. Grader detail: {grades or 'none applicable'}."]
    if example.expected is not None:
        lines.append(f"Expected: {example.expected}")
    lines.append(f"Produced: {output[:400] or '(empty)'}")
    if not output.strip():
        lines.append("The model returned nothing; the instruction may be contradictory.")
    elif grades.get("json_validity") == 0.0:
        lines.append("Output was not valid JSON: the instruction must forbid surrounding prose.")
    elif grades.get("json_schema") == 0.0:
        lines.append(
            "Output parsed but did not match the schema: required fields or types are wrong."
        )
    return "\n".join(lines)


def failure_digest(report) -> str:
    """Re-exported so callers can build the same digest the native loop uses."""
    return _failure_digest(report)


MetricFactory = Callable[..., float]
