from __future__ import annotations

import re
from contextlib import asynccontextmanager
from importlib.resources import files
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, File, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, model_validator

from prompt_playoff import __version__
from prompt_playoff.deployment import DeploymentBundle, export_runtime
from prompt_playoff.domain import (
    AuthorRequest,
    CompiledProgram,
    CompileRequest,
    DescriptionRequest,
    ExecutionTrace,
    Exemplar,
    MeasuredEvidence,
    ModelProfile,
    RunRequest,
    SelectionResult,
    TaskProfile,
    TaskType,
    TechniqueSpec,
)
from prompt_playoff.engine import PromptAuthoringError
from prompt_playoff.evals import BenchmarkExample, load_jsonl_text
from prompt_playoff.experiments import ExperimentComparison, ExperimentRecord
from prompt_playoff.graders import GRADER_HELP, grader_names
from prompt_playoff.integrations import hub
from prompt_playoff.jobs import Job, JobStore
from prompt_playoff.lint import lint_registry, registry_summary
from prompt_playoff.model_profiles import SavedModelProfile
from prompt_playoff.optimizer import BACKENDS
from prompt_playoff.providers import (
    ConnectionCheck,
    InstalledModel,
    ProviderError,
    check_model_connection,
    ollama_models,
)
from prompt_playoff.registry import Registry, RegistryError
from prompt_playoff.service import PromptSelectorService
from prompt_playoff.strategies import aggregator_names, strategy_names
from prompt_playoff.technique_examples import compiled_examples


@asynccontextmanager
async def lifespan(app: FastAPI):
    registry = Registry.load()
    app.state.service = PromptSelectorService(registry)
    app.state.jobs = JobStore()
    yield


app = FastAPI(
    title="Prompt Playoff",
    version=__version__,
    description="Select a prompt technique, compile the prompt it implies, and measure it.",
    lifespan=lifespan,
)

MAX_DATASET_UPLOAD_BYTES = 10 * 1024 * 1024


def _service(request: Request) -> PromptSelectorService:
    return request.app.state.service


def _jobs(request: Request) -> JobStore:
    return request.app.state.jobs


# --------------------------------------------------------------------------- #
# request models
# --------------------------------------------------------------------------- #


class BenchmarkRequest(BaseModel):
    task: TaskProfile
    technique_id: str | None = None
    dataset: str | None = None
    examples: list[BenchmarkExample] = Field(default_factory=list)
    repeats: int = Field(default=1, ge=1, le=10)
    timeout_seconds: float = Field(default=120, gt=0, le=1800)
    record: bool = True


class CompareRequest(BenchmarkRequest):
    technique_ids: list[str] = Field(default_factory=list, max_length=6)


class OptimizeRequest(BenchmarkRequest):
    backend: str = "native"
    rounds: int = Field(default=2, ge=1, le=6)
    candidates_per_round: int = Field(default=3, ge=1, le=6)
    #: native backend only: how many parents the search mutates from each round.
    beam_width: int = Field(default=2, ge=1, le=5)
    validation_ratio: float = Field(default=0.34, gt=0, lt=0.9)
    #: The model that proposes rewrites, never the one being measured.
    engine_model: ModelProfile | None = None
    #: The name `engine_model` shipped under. Kept working; `engine_model` wins.
    optimizer_model: ModelProfile | None = None
    #: DSPy backends only.
    auto: str = "light"
    max_metric_calls: int | None = Field(default=None, ge=4, le=2000)

    @model_validator(mode="after")
    def fold_legacy_optimizer_model(self) -> OptimizeRequest:
        if self.engine_model is None and self.optimizer_model is not None:
            self.engine_model = self.optimizer_model
        return self


class HubSearchRequest(BaseModel):
    description: str = Field(min_length=1, max_length=4000)
    task_type: TaskType | None = None
    #: Used only to phrase the search terms; never sees the dataset rows.
    engine_model: ModelProfile | None = None
    limit: int = Field(default=12, ge=1, le=30)


class HubSearchResponse(BaseModel):
    queries: list[str]
    #: "engine" when the model named the search terms, "keywords" when it could not.
    source: str
    candidates: list[hub.HubCandidate]
    #: Read before the list itself: what these results are worth.
    notes: list[str] = Field(default_factory=list)


class HubImportRequest(BaseModel):
    dataset: str = Field(min_length=1, max_length=200)
    config: str = Field(min_length=1, max_length=200)
    split: str = Field(min_length=1, max_length=100)
    input_column: str = Field(min_length=1, max_length=200)
    expected_column: str | None = Field(default=None, max_length=200)
    limit: int = Field(default=100, ge=2, le=hub.MAX_IMPORT_ROWS)


class PromptfooExportRequest(BaseModel):
    task: TaskProfile
    technique_ids: list[str] = Field(min_length=1, max_length=8)
    dataset: str | None = None
    examples: list[BenchmarkExample] = Field(default_factory=list)
    models: list[ModelProfile] = Field(default_factory=list)
    directory: str = "promptfoo"


class SaveModelProfileRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    profile: ModelProfile
    id: str | None = Field(default=None, max_length=64)


class ExperimentCompareRequest(BaseModel):
    before_id: str
    after_id: str
    technique_id: str | None = None


class DeploymentExportRequest(BaseModel):
    task: TaskProfile
    technique_id: str
    language: str = Field(pattern="^(python|typescript)$")
    response_schema: dict[str, Any] | None = None
    variables: dict[str, str] = Field(default_factory=dict)
    exemplars: list[Exemplar] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# static + introspection
# --------------------------------------------------------------------------- #


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index() -> str:
    return files("prompt_playoff").joinpath("data/static/index.html").read_text(encoding="utf-8")


@app.get("/help", response_class=HTMLResponse, include_in_schema=False)
def help_page() -> str:
    return files("prompt_playoff").joinpath("data/static/help.html").read_text(encoding="utf-8")


@app.get("/help/ru", response_class=HTMLResponse, include_in_schema=False)
def help_page_ru() -> str:
    return files("prompt_playoff").joinpath("data/static/help.ru.html").read_text(encoding="utf-8")


@app.get("/benchmarks", response_class=HTMLResponse, include_in_schema=False)
def benchmarks_page() -> str:
    return (
        files("prompt_playoff").joinpath("data/static/benchmarks.html").read_text(encoding="utf-8")
    )


@app.get("/benchmarks/ru", response_class=HTMLResponse, include_in_schema=False)
def benchmarks_page_ru() -> str:
    return (
        files("prompt_playoff")
        .joinpath("data/static/benchmarks.ru.html")
        .read_text(encoding="utf-8")
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.get("/v1/capabilities")
def capabilities(request: Request) -> dict[str, Any]:
    """Everything a new technique may reference. The extension contract, served."""
    registry = _service(request).registry
    return {
        **registry_summary(registry),
        "aggregators": aggregator_names(),
        "graders": grader_names(),
        #: What each grader measures, so a report can label its numbers in words
        #: instead of leaving the reader to look up a grader name.
        "grader_help": GRADER_HELP,
        "strategies": strategy_names(),
    }


@app.get("/v1/lint")
def lint(request: Request) -> dict[str, Any]:
    issues = lint_registry(_service(request).registry)
    return {
        "ok": not any(issue.level == "error" for issue in issues),
        "issues": [issue.__dict__ for issue in issues],
    }


@app.get("/v1/techniques", response_model=list[TechniqueSpec])
def techniques(request: Request) -> list[TechniqueSpec]:
    return sorted(_service(request).registry.techniques.values(), key=lambda item: item.id)


@app.get("/v1/techniques/examples")
def technique_examples(request: Request) -> list[dict[str, Any]]:
    service = _service(request)
    return compiled_examples(service.compiler, service.registry.techniques)


@app.get("/v1/models", response_model=list[ModelProfile])
def models(request: Request) -> list[ModelProfile]:
    return sorted(
        _service(request).registry.models.values(),
        key=lambda item: (item.provider, item.model_id),
    )


@app.get("/v1/providers/ollama/models", response_model=list[InstalledModel])
async def installed_ollama_models(base_url: str | None = None) -> list[InstalledModel]:
    """The models the local Ollama actually has, for the model field to offer."""
    try:
        return await ollama_models(base_url)
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/v1/providers/check", response_model=ConnectionCheck)
async def check_provider(payload: ModelProfile) -> ConnectionCheck:
    try:
        return await check_model_connection(payload)
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/v1/model-profiles", response_model=list[SavedModelProfile])
def list_model_profiles(request: Request) -> list[SavedModelProfile]:
    return _service(request).profiles.list()


@app.post(
    "/v1/model-profiles", response_model=SavedModelProfile, status_code=status.HTTP_201_CREATED
)
def save_model_profile(payload: SaveModelProfileRequest, request: Request) -> SavedModelProfile:
    try:
        return _service(request).profiles.save(payload.name, payload.profile, payload.id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.delete("/v1/model-profiles/{profile_id}")
def delete_model_profile(profile_id: str, request: Request) -> dict[str, bool]:
    return {"deleted": _service(request).profiles.delete(profile_id)}


@app.get("/v1/datasets")
def datasets(request: Request) -> list[dict[str, Any]]:
    service = _service(request)
    entries: list[dict[str, Any]] = []
    for name in service.dataset_names:
        try:
            examples = service.dataset(name)
        except Exception as exc:
            entries.append({"name": name, "error": str(exc)})
            continue
        entries.append(
            {
                "name": name,
                "examples": len(examples),
                "has_expected": sum(1 for item in examples if item.expected is not None),
                "has_schema": sum(1 for item in examples if item.response_schema is not None),
                "tags": sorted({tag for item in examples for tag in item.tags}),
            }
        )
    return entries


@app.post("/v1/datasets/upload", status_code=status.HTTP_201_CREATED)
async def upload_dataset(request: Request, file: Annotated[UploadFile, File()]) -> dict[str, Any]:
    """Validate a JSONL file and keep it available for this server session."""
    content = await file.read(MAX_DATASET_UPLOAD_BYTES + 1)
    if len(content) > MAX_DATASET_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Dataset exceeds the 10 MiB upload limit")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail="Dataset must be UTF-8 text") from exc
    try:
        examples = load_jsonl_text(text)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not examples:
        raise HTTPException(status_code=422, detail="Dataset contains no BenchmarkExample rows")

    stem = Path(file.filename or "dataset").stem
    slug = re.sub(r"[^a-z0-9._-]+", "-", stem.lower()).strip("-._") or "dataset"
    name = f"uploaded:{slug}"
    # Not persisted: this is the user's own material, arriving from their
    # machine, and writing it out is a promise they have not been asked for.
    _service(request).add_user_dataset(name, examples)
    return {
        "name": name,
        "filename": file.filename,
        "examples": len(examples),
        "has_expected": sum(1 for item in examples if item.expected is not None),
        "has_schema": sum(1 for item in examples if item.response_schema is not None),
    }


# --------------------------------------------------------------------------- #
# Hugging Face Hub: find examples that look like the user's own inputs
#
# The three calls are deliberately separate. Searching is cheap and wrong often
# enough that the user has to see the candidates; previewing shows the columns a
# guess was made from; only the import spends bandwidth and changes state.
# --------------------------------------------------------------------------- #


@app.post("/v1/datasets/hub/search", response_model=HubSearchResponse)
async def hub_search(payload: HubSearchRequest) -> HubSearchResponse:
    # Short leash on the model: naming three search terms is a small ask, and a
    # user waiting on a click would rather have the keyword list than the best
    # possible phrasing from an engine that is swapping or down.
    queries, source = await hub.search_queries(
        payload.description, payload.task_type, payload.engine_model, timeout_seconds=20
    )
    if not queries:
        raise HTTPException(
            status_code=422,
            detail="No search terms could be built from that description. Add a few English "
            "words describing the material, or upload your own examples instead.",
        )
    try:
        candidates = await hub.search(queries, payload.task_type, limit=payload.limit)
    except hub.HubError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    note = hub.generic_result_note(queries, candidates, payload.task_type)
    return HubSearchResponse(
        queries=queries,
        source=source,
        candidates=candidates,
        notes=[note] if note else [],
    )


@app.get("/v1/datasets/hub/preview", response_model=hub.HubPreview)
async def hub_preview(
    dataset: str, config: str | None = None, split: str | None = None
) -> hub.HubPreview:
    try:
        return await hub.preview(dataset, config, split)
    except hub.HubError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/v1/datasets/hub/import", status_code=status.HTTP_201_CREATED)
async def hub_import(request: Request, payload: HubImportRequest) -> dict[str, Any]:
    """Convert Hub rows into examples and keep them for this server session."""
    try:
        rows, columns = await hub.fetch_rows(
            payload.dataset, payload.config, payload.split, payload.limit
        )
    except hub.HubError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    names = [column.name for column in columns]
    for role, column in (("input", payload.input_column), ("expected", payload.expected_column)):
        if column and names and column not in names:
            raise HTTPException(
                status_code=422,
                detail=f"{payload.dataset} has no {role} column {column!r}. Columns: "
                + ", ".join(names),
            )

    raw = hub.to_examples(
        rows, columns, payload.dataset, payload.input_column, payload.expected_column, payload.limit
    )
    if not raw:
        raise HTTPException(
            status_code=422,
            detail=f"No usable rows in {payload.dataset}: every row was missing its "
            f"{payload.input_column!r} value or its answer.",
        )
    examples = [BenchmarkExample.model_validate(item) for item in raw]
    name = f"hf:{payload.dataset}"
    # Persisted: these rows are public, and re-importing them means repeating a
    # download and the column decisions the user just made by hand.
    saved = _service(request).add_user_dataset(name, examples, persist=True)
    return {
        "name": name,
        "dataset": payload.dataset,
        "config": payload.config,
        "split": payload.split,
        "examples": len(examples),
        "has_expected": sum(1 for item in examples if item.expected is not None),
        "skipped": len(rows) - len(examples),
        "saved_to": str(saved) if saved else None,
    }


# `:path` because an imported Hub dataset is named after its repo, and a repo id
# carries a slash. Declared after the /hub/ routes, which therefore still win.
@app.get("/v1/datasets/{name:path}", response_model=list[BenchmarkExample])
def dataset_examples(name: str, request: Request) -> list[BenchmarkExample]:
    try:
        return _service(request).dataset(name)
    except RegistryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/v1/measurements", response_model=list[MeasuredEvidence])
def measurements(request: Request) -> list[MeasuredEvidence]:
    return _service(request).measurements.records


# --------------------------------------------------------------------------- #
# selection, compilation, execution
# --------------------------------------------------------------------------- #


@app.post("/v1/recommend", response_model=SelectionResult)
async def recommend(payload: DescriptionRequest, request: Request) -> SelectionResult:
    result, _ = await _service(request).recommend(
        description=payload.description,
        model=payload.model,
        overrides=payload.overrides,
        engine_model=payload.engine_model,
    )
    return result


@app.post("/v1/select", response_model=SelectionResult)
def select(payload: TaskProfile, request: Request) -> SelectionResult:
    return _service(request).select(payload)


@app.post("/v1/compile", response_model=CompiledProgram)
def compile_prompt(payload: CompileRequest, request: Request) -> CompiledProgram:
    try:
        return _service(request).compile(payload)
    except (ValueError, RegistryError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/author", response_model=CompiledProgram)
async def author_prompt(payload: AuthorRequest, request: Request) -> CompiledProgram:
    """Use an engine LLM to write prompt text; never substitute a compiler fallback."""
    try:
        return await _service(request).author(payload)
    except PromptAuthoringError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except (ValueError, RegistryError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/run", response_model=ExecutionTrace)
async def run_prompt(payload: RunRequest, request: Request) -> ExecutionTrace:
    try:
        return await _service(request).run(payload)
    except (ValueError, RegistryError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# --------------------------------------------------------------------------- #
# measurement jobs
# --------------------------------------------------------------------------- #


@app.post("/v1/benchmark", response_model=Job)
async def start_benchmark(payload: BenchmarkRequest, request: Request) -> Job:
    service, store = _service(request), _jobs(request)
    job = store.create("benchmark")

    async def work() -> dict[str, Any]:
        report = await service.benchmark(
            task=payload.task,
            technique_id=payload.technique_id,
            dataset_name=payload.dataset,
            inline=payload.examples or None,
            repeats=payload.repeats,
            timeout_seconds=payload.timeout_seconds,
            record=payload.record,
            progress=lambda event: store.note(job.id, event),
        )
        return report.model_dump(mode="json")

    return store.start(job, work)


@app.post("/v1/compare", response_model=Job)
async def start_compare(payload: CompareRequest, request: Request) -> Job:
    service, store = _service(request), _jobs(request)
    if len(payload.technique_ids) < 2:
        raise HTTPException(status_code=422, detail="Provide at least two technique_ids")
    job = store.create("compare")

    async def work() -> dict[str, Any]:
        comparison, reports = await service.compare(
            task=payload.task,
            technique_ids=payload.technique_ids,
            dataset_name=payload.dataset,
            inline=payload.examples or None,
            repeats=payload.repeats,
            timeout_seconds=payload.timeout_seconds,
            record=payload.record,
            progress=lambda event: store.note(job.id, event),
        )
        return {
            "comparison": comparison.model_dump(mode="json"),
            "reports": [item.model_dump(mode="json") for item in reports],
        }

    return store.start(job, work)


@app.post("/v1/optimize", response_model=Job)
async def start_optimize(payload: OptimizeRequest, request: Request) -> Job:
    service, store = _service(request), _jobs(request)
    if payload.backend not in BACKENDS:
        raise HTTPException(
            status_code=422, detail=f"Unknown backend. Known: {', '.join(BACKENDS)}"
        )
    job = store.create(f"optimize:{payload.backend}")

    async def work() -> dict[str, Any]:
        result = await service.optimize(
            task=payload.task,
            technique_id=payload.technique_id,
            dataset_name=payload.dataset,
            inline=payload.examples or None,
            backend=payload.backend,
            rounds=payload.rounds,
            candidates_per_round=payload.candidates_per_round,
            beam_width=payload.beam_width,
            repeats=payload.repeats,
            validation_ratio=payload.validation_ratio,
            timeout_seconds=payload.timeout_seconds,
            engine_model=payload.engine_model,
            max_metric_calls=payload.max_metric_calls,
            auto=payload.auto,
            record=payload.record,
            progress=lambda event: store.note(job.id, event),
        )
        return result.model_dump(mode="json")

    return store.start(job, work)


@app.get("/v1/experiments", response_model=list[ExperimentRecord])
def list_experiments(request: Request) -> list[ExperimentRecord]:
    return _service(request).experiments.list()


@app.post("/v1/experiments/compare", response_model=ExperimentComparison)
def compare_experiments(
    payload: ExperimentCompareRequest, request: Request
) -> ExperimentComparison:
    try:
        return _service(request).experiments.compare(
            payload.before_id, payload.after_id, payload.technique_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/v1/experiments/{experiment_id}", response_model=ExperimentRecord)
def get_experiment(experiment_id: str, request: Request) -> ExperimentRecord:
    record = _service(request).experiments.get(experiment_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Unknown experiment")
    return record


@app.post("/v1/export/promptfoo")
def export_promptfoo(payload: PromptfooExportRequest, request: Request) -> dict[str, Any]:
    """Write a promptfoo project to disk and report what landed where."""
    service = _service(request)
    try:
        result = service.export_promptfoo(
            directory=Path(payload.directory),
            task=payload.task,
            technique_ids=payload.technique_ids,
            dataset_name=payload.dataset,
            inline=payload.examples or None,
            models=payload.models or [payload.task.model],
        )
    except (ValueError, RegistryError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "config": str(result.config_path),
        "prompts": [str(path) for path in result.prompt_paths],
        "asserts": str(result.bridge_path),
        "warnings": result.warnings,
        "next": f"cd {payload.directory} && promptfoo eval && promptfoo view",
    }


@app.post("/v1/export/runtime", response_model=DeploymentBundle)
def export_deployment(payload: DeploymentExportRequest, request: Request) -> DeploymentBundle:
    try:
        _service(request).resolve_technique(payload.task, payload.technique_id)
        return export_runtime(
            task=payload.task,
            technique_id=payload.technique_id,
            language=payload.language,  # type: ignore[arg-type]
            response_schema=payload.response_schema,
            variables=payload.variables,
            exemplars=payload.exemplars,
        )
    except (ValueError, RegistryError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/v1/integrations")
def integrations(request: Request) -> dict[str, Any]:
    """What is installed and configured, so a client can hide what will not work."""
    import os

    from prompt_playoff.integrations import installed

    return {
        "optimizer_backends": list(BACKENDS),
        "dspy": {
            "installed": installed("dspy"),
            "optimizers": ["mipro", "gepa", "bootstrap"],
        },
        "promptfoo": {"export": True},
        "tracing": {
            "active": os.getenv("PROMPT_PLAYOFF_TRACING", "none"),
            "backend": type(_service(request).tracer).__name__,
            "langfuse_installed": installed("langfuse"),
            "otel_installed": installed("opentelemetry.sdk"),
        },
    }


@app.get("/v1/jobs", response_model=list[Job])
def list_jobs(request: Request) -> list[Job]:
    return _jobs(request).list()


@app.get("/v1/jobs/{job_id}", response_model=Job)
def get_job(job_id: str, request: Request) -> Job:
    job = _jobs(request).get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job")
    return job


@app.delete("/v1/jobs/{job_id}")
def cancel_job(job_id: str, request: Request) -> dict[str, bool]:
    return {"cancelled": _jobs(request).cancel(job_id)}
