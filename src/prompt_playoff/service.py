from __future__ import annotations

from pathlib import Path
from typing import Any

from prompt_playoff.compiler import PromptCompiler
from prompt_playoff.dataset_store import DatasetStore
from prompt_playoff.domain import (
    AuthorRequest,
    CompiledProgram,
    CompileRequest,
    ExecutionTrace,
    ModelProfile,
    RunRequest,
    SelectionResult,
    TaskProfile,
    TaskType,
    TechniqueSpec,
)
from prompt_playoff.engine import TaskEngine, TaskNormalization, resolve_engine_profile
from prompt_playoff.evals import (
    BenchmarkExample,
    BenchmarkReport,
    BenchmarkRunner,
    ComparisonReport,
    ProgressCallback,
    compare_techniques,
    load_jsonl,
)
from prompt_playoff.experiments import ExperimentStore
from prompt_playoff.integrations.tracing import (
    NullTracer,
    Tracer,
    TracingProvider,
    tracer_from_env,
)
from prompt_playoff.measurements import MeasurementStore
from prompt_playoff.model_profiles import ModelProfileStore
from prompt_playoff.optimizer import BACKENDS, OptimizationResult, PromptOptimizer
from prompt_playoff.providers import ModelProvider, provider_for
from prompt_playoff.registry import Registry
from prompt_playoff.selector import Selector
from prompt_playoff.strategies import get_strategy


class PromptSelectorService:
    def __init__(
        self,
        registry: Registry,
        measurements: MeasurementStore | None = None,
        tracer: Tracer | None = None,
        datasets: DatasetStore | None = None,
        experiments: ExperimentStore | None = None,
        profiles: ModelProfileStore | None = None,
    ) -> None:
        self.registry = registry
        self.measurements = measurements if measurements is not None else MeasurementStore()
        self.selector = Selector(registry, self.measurements)
        self.compiler = PromptCompiler()
        self.tracer = tracer if tracer is not None else tracer_from_env()
        self.dataset_store = datasets if datasets is not None else DatasetStore()
        self.experiments = experiments if experiments is not None else ExperimentStore()
        self.profiles = profiles if profiles is not None else ModelProfileStore()
        #: Datasets the user brought in, whether saved to disk on a previous run
        #: or added during this one. Shadow the packaged datasets by name.
        self.user_datasets: dict[str, list[BenchmarkExample]] = self.dataset_store.load()

    def provider(self, task: TaskProfile, **metadata) -> ModelProvider:
        """Every provider goes through here, so tracing is never bypassed."""
        base = provider_for(task.model)
        if isinstance(self.tracer, NullTracer):
            return base
        return TracingProvider(
            base,
            self.tracer,
            metadata={"task_type": task.task_type.value, **metadata},
        )

    # -- the engine model ---------------------------------------------------- #

    def engine(self, engine_model: ModelProfile | None = None) -> TaskEngine:
        """Resolve the engine once, here, so no caller invents its own fallback."""
        profile = resolve_engine_profile(engine_model)
        provider = None
        if profile is not None:
            provider = self.provider(
                TaskProfile(task_type=TaskType.summarization, model=profile),
                phase="engine",
            )
        return TaskEngine(profile, provider=provider)

    async def normalize(
        self,
        description: str,
        model: ModelProfile,
        overrides: dict[str, Any] | None = None,
        engine_model: ModelProfile | None = None,
        timeout_seconds: float = 120,
    ) -> TaskNormalization:
        return await self.engine(engine_model).normalize(
            description, model, overrides, timeout_seconds=timeout_seconds
        )

    # -- selection ---------------------------------------------------------- #

    def select(self, task: TaskProfile, limit: int = 3) -> SelectionResult:
        return self.selector.select(task, limit=limit)

    async def recommend(
        self,
        description: str,
        model: ModelProfile,
        overrides: dict[str, Any] | None = None,
        engine_model: ModelProfile | None = None,
        limit: int = 3,
    ) -> tuple[SelectionResult, TaskNormalization]:
        """Read the description, then rank. How the profile was read is part of the answer."""
        normalization = await self.normalize(description, model, overrides, engine_model)
        result = self.select(normalization.profile, limit=limit)
        if normalization.notes:
            result = result.model_copy(
                update={"warnings": [*normalization.notes, *result.warnings]}
            )
        return result, normalization

    def resolve_technique(self, task: TaskProfile, technique_id: str | None) -> TechniqueSpec:
        if technique_id is None:
            selection = self.select(task, limit=1)
            if not selection.recommendations:
                raise ValueError("No compatible technique found")
            technique_id = selection.recommendations[0].technique_id
        return self.registry.technique(technique_id)

    # -- compilation and execution ------------------------------------------ #

    def compile(self, request: CompileRequest) -> CompiledProgram:
        technique = self.resolve_technique(request.task, request.technique_id)
        return self.compiler.compile(
            task=request.task,
            technique=technique,
            user_input=request.user_input,
            response_schema=request.response_schema,
            variables=request.variables,
            exemplars=request.exemplars,
        )

    async def author(self, request: AuthorRequest) -> CompiledProgram:
        """Compile the contract, then have the engine author its actual message text."""
        task = _with_runtime_material(request.task) if request.reusable else request.task
        technique = self.resolve_technique(task, request.technique_id)
        user_input = "{input}" if request.reusable else request.description
        scaffold = self.compiler.compile(
            task=task,
            technique=technique,
            user_input=user_input,
            response_schema=request.response_schema,
            variables=request.variables,
            exemplars=request.exemplars,
        )
        return await self.engine(request.engine_model).author(
            description=request.description,
            technique=technique,
            scaffold=scaffold,
            reusable=request.reusable,
            timeout_seconds=request.timeout_seconds,
        )

    async def run(self, request: RunRequest) -> ExecutionTrace:
        program = self.compile(request)
        strategy = get_strategy(program.strategy)
        provider = self.provider(request.task, technique_id=program.technique_id)
        return await strategy.execute(
            program=program,
            task=request.task,
            provider=provider,
            timeout_seconds=request.timeout_seconds,
        )

    # -- measurement -------------------------------------------------------- #

    def dataset(self, name: str) -> list[BenchmarkExample]:
        if name in self.user_datasets:
            return list(self.user_datasets[name])
        return load_jsonl(self.registry.dataset_path(name))

    def add_user_dataset(
        self, name: str, examples: list[BenchmarkExample], persist: bool = False
    ) -> Path | None:
        """Register validated examples, optionally keeping them across restarts.

        ``persist`` is the caller's decision rather than a default, because
        writing rows to disk is not the same promise for public Hub data as it
        is for a file the user dropped in from their own machine.
        """
        self.user_datasets[name] = list(examples)
        return self.dataset_store.save(name, examples) if persist else None

    @property
    def dataset_names(self) -> list[str]:
        return sorted({*self.registry.datasets, *self.user_datasets})

    def resolve_dataset(
        self,
        name: str | None,
        inline: list[BenchmarkExample] | None,
    ) -> tuple[list[BenchmarkExample], str]:
        if inline:
            return inline, "inline"
        if name:
            return self.dataset(name), name
        raise ValueError("Provide either a dataset name or inline examples")

    async def benchmark(
        self,
        task: TaskProfile,
        technique_id: str | None,
        dataset_name: str | None = None,
        inline: list[BenchmarkExample] | None = None,
        repeats: int = 1,
        timeout_seconds: float = 120,
        record: bool = True,
        progress: ProgressCallback | None = None,
    ) -> BenchmarkReport:
        technique = self.resolve_technique(task, technique_id)
        examples, name = self.resolve_dataset(dataset_name, inline)
        runner = BenchmarkRunner(
            self.provider(task, technique_id=technique.id, phase="benchmark"), self.compiler
        )
        report = await runner.run(
            dataset=examples,
            task=task,
            technique=technique,
            repeats=repeats,
            timeout_seconds=timeout_seconds,
            dataset_name=name,
            progress=progress,
        )
        if record:
            self.measurements.record(report.to_evidence())
            self.experiments.add_benchmark(report, task)
        return report

    async def compare(
        self,
        task: TaskProfile,
        technique_ids: list[str],
        dataset_name: str | None = None,
        inline: list[BenchmarkExample] | None = None,
        repeats: int = 1,
        timeout_seconds: float = 120,
        record: bool = True,
        progress: ProgressCallback | None = None,
    ) -> tuple[ComparisonReport, list[BenchmarkReport]]:
        techniques = [self.registry.technique(item) for item in technique_ids]
        examples, name = self.resolve_dataset(dataset_name, inline)
        comparison, reports = await compare_techniques(
            dataset=examples,
            task=task,
            techniques=techniques,
            provider=self.provider(task, phase="compare"),
            repeats=repeats,
            timeout_seconds=timeout_seconds,
            dataset_name=name,
            progress=progress,
        )
        if record:
            for report in reports:
                self.measurements.record(report.to_evidence())
            self.experiments.add_comparison(comparison, reports, task)
        return comparison, reports

    async def optimize(
        self,
        task: TaskProfile,
        technique_id: str | None,
        dataset_name: str | None = None,
        inline: list[BenchmarkExample] | None = None,
        backend: str = "native",
        rounds: int = 2,
        candidates_per_round: int = 3,
        beam_width: int = 2,
        repeats: int = 1,
        validation_ratio: float = 0.34,
        timeout_seconds: float = 120,
        engine_model: ModelProfile | None = None,
        max_metric_calls: int | None = None,
        auto: str = "light",
        record: bool = True,
        progress: ProgressCallback | None = None,
    ) -> OptimizationResult:
        """Search for a better prompt. `backend` picks the search algorithm only —
        compilation, execution and grading are the same either way."""
        technique = self.resolve_technique(task, technique_id)
        examples, name = self.resolve_dataset(dataset_name, inline)
        provider = self.provider(task, technique_id=technique.id, phase="optimize")
        #: A full profile of its own: the proposer may be a remote model while the
        #: target is local, so nothing here may be inherited from the target.
        engine_profile = resolve_engine_profile(engine_model)

        if backend == "native":
            optimizer = PromptOptimizer(
                provider=provider,
                engine_provider=(
                    self.provider(
                        task.model_copy(update={"model": engine_profile}),
                        technique_id=technique.id,
                        phase="propose",
                    )
                    if engine_profile
                    else None
                ),
                engine_model=engine_profile,
                compiler=self.compiler,
            )
            result = await optimizer.optimize(
                task=task,
                technique=technique,
                dataset=examples,
                rounds=rounds,
                candidates_per_round=candidates_per_round,
                beam_width=beam_width,
                repeats=repeats,
                validation_ratio=validation_ratio,
                timeout_seconds=timeout_seconds,
                dataset_name=name,
                progress=progress,
            )
            if record:
                self.experiments.add_optimization(result, task)
            return result

        if not backend.startswith("dspy:"):
            raise ValueError(f"Unknown backend {backend!r}. Known: {', '.join(BACKENDS)}")

        from prompt_playoff.integrations.dspy_backend import optimize_with_dspy

        result = await optimize_with_dspy(
            task=task,
            technique=technique,
            dataset=examples,
            provider=provider,
            optimizer=backend.split(":", 1)[1],
            auto=auto,  # type: ignore[arg-type]
            max_metric_calls=max_metric_calls,
            repeats=repeats,
            validation_ratio=validation_ratio,
            timeout_seconds=timeout_seconds,
            dataset_name=name,
            proposer_model=engine_profile,
            compiler=self.compiler,
            progress=progress,
        )
        if record:
            self.experiments.add_optimization(result, task)
        return result

    def export_promptfoo(
        self,
        directory: Path,
        task: TaskProfile,
        technique_ids: list[str],
        dataset_name: str | None = None,
        inline: list[BenchmarkExample] | None = None,
        models: list[ModelProfile] | None = None,
    ):
        from prompt_playoff.integrations import promptfoo

        examples, name = self.resolve_dataset(dataset_name, inline)
        techniques = [self.registry.technique(item) for item in technique_ids]
        return promptfoo.export(
            directory=directory,
            task=task,
            techniques=techniques,
            dataset=examples,
            models=models or [task.model],
            dataset_name=name,
        )

    def save_report(self, report: BenchmarkReport, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        stamp = report.finished_at.replace(":", "").replace("-", "")
        slug = report.technique_id.replace(".", "-")
        path = (
            directory
            / f"{slug}__{report.model_id.replace(':', '-').replace('/', '-')}__{stamp}.json"
        )
        path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        return path


def _with_runtime_material(task: TaskProfile) -> TaskProfile:
    """A reusable template's `{input}` is the material, whatever the request said.

    Selection otherwise reads "this request supplies nothing to work on" and rules
    out every recipe that reads an input — which is exactly what a template is for.
    """
    return task.model_copy(
        update={"constraints": task.constraints.model_copy(update={"supplied_material": True})}
    )
