from __future__ import annotations

import re
from contextlib import asynccontextmanager
from importlib.resources import files
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, File, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from prompt_selector import __version__
from prompt_selector.domain import (
    CompiledProgram,
    CompileRequest,
    DescriptionRequest,
    ExecutionTrace,
    MeasuredEvidence,
    ModelProfile,
    RunRequest,
    SelectionResult,
    TaskProfile,
    TechniqueSpec,
)
from prompt_selector.evals import BenchmarkExample, load_jsonl_text
from prompt_selector.graders import grader_names
from prompt_selector.jobs import Job, JobStore
from prompt_selector.lint import lint_registry, registry_summary
from prompt_selector.normalizer import normalize_description
from prompt_selector.optimizer import BACKENDS
from prompt_selector.providers import ProviderError
from prompt_selector.registry import Registry, RegistryError
from prompt_selector.service import PromptSelectorService
from prompt_selector.strategies import aggregator_names, strategy_names


@asynccontextmanager
async def lifespan(app: FastAPI):
    registry = Registry.load()
    app.state.service = PromptSelectorService(registry)
    app.state.jobs = JobStore()
    yield


app = FastAPI(
    title="Prompt Selector",
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
    optimizer_model: ModelProfile | None = None
    #: DSPy backends only.
    auto: str = "light"
    max_metric_calls: int | None = Field(default=None, ge=4, le=2000)


class PromptfooExportRequest(BaseModel):
    task: TaskProfile
    technique_ids: list[str] = Field(min_length=1, max_length=8)
    dataset: str | None = None
    examples: list[BenchmarkExample] = Field(default_factory=list)
    models: list[ModelProfile] = Field(default_factory=list)
    directory: str = "promptfoo"


# --------------------------------------------------------------------------- #
# static + introspection
# --------------------------------------------------------------------------- #


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index() -> str:
    return files("prompt_selector").joinpath("data/static/index.html").read_text(encoding="utf-8")


@app.get("/help", response_class=HTMLResponse, include_in_schema=False)
def help_page() -> str:
    return files("prompt_selector").joinpath("data/static/help.html").read_text(encoding="utf-8")


@app.get("/help/en", response_class=HTMLResponse, include_in_schema=False)
def help_page_en() -> str:
    return files("prompt_selector").joinpath("data/static/help.en.html").read_text(encoding="utf-8")


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


@app.get("/v1/models", response_model=list[ModelProfile])
def models(request: Request) -> list[ModelProfile]:
    return sorted(
        _service(request).registry.models.values(),
        key=lambda item: (item.provider, item.model_id),
    )


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
    _service(request).add_session_dataset(name, examples)
    return {
        "name": name,
        "filename": file.filename,
        "examples": len(examples),
        "has_expected": sum(1 for item in examples if item.expected is not None),
        "has_schema": sum(1 for item in examples if item.response_schema is not None),
    }


@app.get("/v1/datasets/{name}", response_model=list[BenchmarkExample])
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
def recommend(payload: DescriptionRequest, request: Request) -> SelectionResult:
    task = normalize_description(payload.description, payload.model, payload.overrides)
    return _service(request).select(task)


@app.post("/v1/select", response_model=SelectionResult)
def select(payload: TaskProfile, request: Request) -> SelectionResult:
    return _service(request).select(payload)


@app.post("/v1/compile", response_model=CompiledProgram)
def compile_prompt(payload: CompileRequest, request: Request) -> CompiledProgram:
    try:
        return _service(request).compile(payload)
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
            optimizer_model=payload.optimizer_model,
            max_metric_calls=payload.max_metric_calls,
            auto=payload.auto,
            progress=lambda event: store.note(job.id, event),
        )
        return result.model_dump(mode="json")

    return store.start(job, work)


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


@app.get("/v1/integrations")
def integrations(request: Request) -> dict[str, Any]:
    """What is installed and configured, so a client can hide what will not work."""
    import importlib.util
    import os

    return {
        "optimizer_backends": list(BACKENDS),
        "dspy": {
            "installed": importlib.util.find_spec("dspy") is not None,
            "optimizers": ["mipro", "gepa", "bootstrap"],
        },
        "promptfoo": {"export": True},
        "tracing": {
            "active": os.getenv("PROMPT_SELECTOR_TRACING", "none"),
            "backend": type(_service(request).tracer).__name__,
            "langfuse_installed": importlib.util.find_spec("langfuse") is not None,
            "otel_installed": importlib.util.find_spec("opentelemetry.sdk") is not None,
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
