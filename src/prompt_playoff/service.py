from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from prompt_playoff.business_cases import BusinessCaseRecord, BusinessCaseStore
from prompt_playoff.compiler import PromptCompiler
from prompt_playoff.dataset_store import DatasetStore
from prompt_playoff.domain import (
    AdoptOptimizedRequest,
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
    authored_for,
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
from prompt_playoff.optimizer import (
    BACKENDS,
    OptimizationResult,
    PromptOptimizer,
    refuse_unmeasurable,
)
from prompt_playoff.providers import ModelProvider, provider_for
from prompt_playoff.registry import Registry
from prompt_playoff.selector import Selector
from prompt_playoff.strategies import get_strategy
from prompt_playoff.technique_store import TechniqueStore


class TechniqueNameConflict(ValueError):
    """A saved technique would take a name that already means something else."""


class PromptSelectorService:
    def __init__(
        self,
        registry: Registry,
        measurements: MeasurementStore | None = None,
        tracer: Tracer | None = None,
        datasets: DatasetStore | None = None,
        experiments: ExperimentStore | None = None,
        profiles: ModelProfileStore | None = None,
        techniques: TechniqueStore | None = None,
        business_cases: BusinessCaseStore | None = None,
    ) -> None:
        self.registry = registry
        self.measurements = measurements if measurements is not None else MeasurementStore()
        self.selector = Selector(registry, self.measurements)
        self.compiler = PromptCompiler()
        self.tracer = tracer if tracer is not None else tracer_from_env()
        self.dataset_store = datasets if datasets is not None else DatasetStore()
        self.experiments = experiments if experiments is not None else ExperimentStore()
        self.profiles = profiles if profiles is not None else ModelProfileStore()
        self.business_cases = business_cases if business_cases is not None else BusinessCaseStore()
        #: Datasets the user brought in, whether saved to disk on a previous run
        #: or added during this one. Shadow the packaged datasets by name.
        self.user_datasets: dict[str, list[BenchmarkExample]] = self.dataset_store.load()
        self.technique_store = techniques if techniques is not None else TechniqueStore()
        #: Optimization winners saved for later. Resolvable by id, and left out
        #: of ranking on purpose — see `technique_store`.
        self.user_techniques: dict[str, TechniqueSpec] = self.technique_store.load()

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
        # A saved optimization winner is never recommended, but it has to be
        # resolvable, or every path that takes a technique id — run, benchmark,
        # runtime export — would refuse the thing the search produced.
        if saved := self.user_techniques.get(technique_id):
            return saved
        return self.registry.technique(technique_id)

    @property
    def all_techniques(self) -> dict[str, TechniqueSpec]:
        """Everything resolvable by id: the registry, then what was saved here."""
        return {**self.registry.techniques, **self.user_techniques}

    def save_technique(self, payload: dict[str, Any], technique_id: str | None = None) -> Path:
        """Persist an optimization winner so the rest of the tool can resolve it.

        A saved id may not shadow a registry recipe: everyone else's runs resolve
        that id too, and silently changing what it means would rewrite the
        meaning of numbers already recorded under it.
        """
        try:
            spec = TechniqueSpec.model_validate(payload)
        except ValidationError as exc:
            raise ValueError(f"This is not a technique the optimizer produced: {exc}") from exc
        if technique_id:
            spec = spec.model_copy(update={"id": technique_id})
        if spec.id in self.registry.techniques:
            raise TechniqueNameConflict(
                f"{spec.id} is a registry recipe. Save the winner under a name of its own "
                "so the recipe it came from keeps meaning what it meant."
            )
        path = self.technique_store.save(spec)
        self.user_techniques[spec.id] = spec
        return path

    def remove_technique(self, technique_id: str) -> Path | None:
        """Only what was saved here can go; the packaged recipes are not ours to delete."""
        if technique_id not in self.user_techniques:
            raise KeyError(technique_id)
        path = self.technique_store.path_for(technique_id)
        removed = path if self.technique_store.remove(technique_id) else None
        del self.user_techniques[technique_id]
        return removed

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

    def adopt_optimized(self, request: AdoptOptimizedRequest) -> CompiledProgram:
        """Recompile this task through the instruction blocks the search won with.

        The optimizer's own preview cannot be adopted directly: it was compiled
        against a dataset row, so copying it would bake a benchmark example into
        the prompt. What travels is the winning technique, and the identity of
        the registry technique it came from stays on the program — a prompt with
        an id nothing can resolve cannot be measured, run, or exported.
        """
        if request.program is not None:
            # Nothing to recompile: the search measured this exact text for this
            # task. Recompiling it would throw away the thing that was measured.
            try:
                program = CompiledProgram.model_validate(request.program)
            except ValidationError as exc:
                raise ValueError(f"This is not a prompt the optimizer produced: {exc}") from exc
            self.resolve_technique(request.task, program.technique_id)
            return program.model_copy(
                update={
                    "artifact_source": "optimizer",
                    "authored_by_model": request.engine_model_id,
                }
            )
        if not request.technique:
            raise ValueError("Give either the winning technique or the winning prompt")
        base = self.resolve_technique(request.task, request.technique_id)
        try:
            technique = TechniqueSpec.model_validate(
                {
                    **request.technique,
                    "id": base.id,
                    "title": base.title,
                    "version": base.version,
                }
            )
        except ValidationError as exc:
            raise ValueError(f"This is not a technique the optimizer produced: {exc}") from exc
        task = _with_runtime_material(request.task) if request.reusable else request.task
        user_input = "{input}" if request.reusable else request.description
        if not user_input.strip():
            raise ValueError("Give the task's own material, or adopt the prompt as a template")
        program = self.compiler.compile(
            task=task,
            technique=technique,
            user_input=user_input,
            response_schema=request.response_schema,
            variables=request.variables,
            exemplars=request.exemplars,
        )
        return program.model_copy(
            update={
                "artifact_source": "optimizer",
                "authored_by_model": request.engine_model_id,
            }
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

    def remove_user_dataset(self, name: str) -> Path | None:
        """Forget a set the user brought in, and delete its file if it had one.

        Only the user's own sets can go: a bundled set lives inside the installed
        package, and deleting it would leave the server describing a registry it
        no longer has.
        """
        if name not in self.user_datasets:
            raise KeyError(name)
        removed = self.dataset_store.path_for(name) if self.dataset_store.remove(name) else None
        del self.user_datasets[name]
        return removed

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
        prompt: CompiledProgram | None = None,
        business_case: BusinessCaseRecord | None = None,
    ) -> BenchmarkReport:
        technique = self.resolve_technique(task, technique_id)
        examples, name = self.resolve_dataset(dataset_name, inline)
        if prompt is not None:
            self._check_measurable(prompt, technique, examples)
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
            authored=prompt,
        )
        if record:
            self.measurements.record(report.to_evidence())
            # The report carries its own record id: a release registered from
            # this prompt has to be able to name the run that justified it.
            report.experiment_id = self.experiments.add_benchmark(
                report,
                task,
                business_case=business_case,
                prompt_snapshot=prompt.model_dump(mode="json") if prompt is not None else None,
            ).id
        return report

    @staticmethod
    def _check_measurable(
        prompt: CompiledProgram,
        technique: TechniqueSpec,
        examples: list[BenchmarkExample],
    ) -> None:
        """Refuse a supplied prompt now, rather than partway through the run.

        Two ways it cannot be used: filed under a method it was not written from,
        which puts the numbers under the wrong name; and written with nowhere for
        an example's input to go, which `authored_for` can only discover row by
        row — in the middle of a job that has already spent model calls.
        """
        if prompt.technique_id != technique.id:
            raise ValueError(
                f"This prompt was written from {prompt.technique_id}, "
                f"but the run was asked for {technique.id}."
            )
        if examples:
            authored_for(prompt, examples[0])

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
        prompt: CompiledProgram | None = None,
        business_case: BusinessCaseRecord | None = None,
    ) -> tuple[ComparisonReport, list[BenchmarkReport]]:
        techniques = [self.resolve_technique(task, item) for item in technique_ids]
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
            authored=prompt,
        )
        if record:
            for report in reports:
                self.measurements.record(report.to_evidence())
            self.experiments.add_comparison(
                comparison,
                reports,
                task,
                business_case=business_case,
                prompt_snapshot=prompt.model_dump(mode="json") if prompt is not None else None,
            )
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
        prompt: CompiledProgram | None = None,
        business_case: BusinessCaseRecord | None = None,
        allow_noisy_objective: bool = False,
    ) -> OptimizationResult:
        """Search for a better prompt. `backend` picks the search algorithm only —
        compilation, execution and grading are the same either way.

        `prompt` is the text the caller is holding, and it becomes the baseline —
        the same contract `benchmark` has. Sending it is what makes "improvement"
        a statement about your prompt rather than about a compile of the recipe.
        """
        technique = self.resolve_technique(task, technique_id)
        examples, name = self.resolve_dataset(dataset_name, inline)
        # Before the backend is chosen, because either of them would spend the
        # same evening of calls raising a number that cannot decide anything.
        # Measuring such a set stays allowed — a number read correctly is still
        # a number. Searching against it is what produces a worse prompt.
        refuse_unmeasurable(examples, allowed=allow_noisy_objective)
        if prompt is not None:
            self._check_measurable(prompt, technique, examples)
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
                allow_noisy_objective=allow_noisy_objective,
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
                authored=prompt,
            )
            if record:
                result.experiment_id = self.experiments.add_optimization(
                    result, task, business_case=business_case
                ).id
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
            authored=prompt,
        )
        if record:
            result.experiment_id = self.experiments.add_optimization(
                result, task, business_case=business_case
            ).id
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
        techniques = [self.resolve_technique(task, item) for item in technique_ids]
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
