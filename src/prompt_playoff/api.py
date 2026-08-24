from __future__ import annotations

import asyncio
import json
import random
import re
import uuid
from collections import Counter
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, metadata
from importlib.resources import files
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field, ValidationError, model_validator

from prompt_playoff import __version__
from prompt_playoff.business_cases import BusinessCaseRecord
from prompt_playoff.business_catalog import CatalogError, catalog
from prompt_playoff.checks import ReleaseGate, release_gate
from prompt_playoff.contracts import apply_requirements
from prompt_playoff.deployment import (
    DeploymentBundle,
    ReleaseManifest,
    export_runtime,
    release_manifest,
)
from prompt_playoff.domain import (
    AdoptOptimizedRequest,
    AuthorRequest,
    CompiledProgram,
    CompiledPrompt,
    CompileRequest,
    DescriptionRequest,
    ExecutionTrace,
    Exemplar,
    MeasuredEvidence,
    Message,
    ModelProfile,
    RunRequest,
    SelectionResult,
    TaskProfile,
    TaskType,
    TechniqueSpec,
)
from prompt_playoff.engine import PromptAuthoringError
from prompt_playoff.evals import (
    BenchmarkExample,
    ExampleRun,
    dataset_revision,
    load_jsonl_text,
    overlap_scored_references,
    prompt_fingerprint,
)
from prompt_playoff.experiments import ExperimentComparison, ExperimentRecord, experiments_csv
from prompt_playoff.graders import (
    GRADER_CAVEATS,
    GRADER_HELP,
    PASS_RATE_GRADERS,
    QUALITY_PREFERENCE,
    REFERENCE_OVERLAP_GRADERS,
    RELIABILITY_GRADERS,
    grader_names,
    headline_grader,
    token_f1_chance_level,
)
from prompt_playoff.integrations import hub
from prompt_playoff.integrations.huggingface import CODE_PRESETS as HF_CODE_PRESETS
from prompt_playoff.integrations.huggingface import PRESETS as HF_PRESETS
from prompt_playoff.integrations.huggingface import QA_PRESETS as HF_QA_PRESETS
from prompt_playoff.integrations.tracing import import_langfuse_dataset
from prompt_playoff.jobs import Job, JobStore
from prompt_playoff.lint import lint_registry, registry_summary
from prompt_playoff.model_profiles import SavedModelProfile
from prompt_playoff.optimizer import (
    BACKENDS,
    UnmeasurableObjective,
    refuse_unmeasurable,
)
from prompt_playoff.providers import (
    ConnectionCheck,
    InstalledModel,
    ProviderError,
    check_model_connection,
    embed_texts,
    ollama_models,
)
from prompt_playoff.quality import (
    PERSONAS,
    DataMix,
    DatasetBuildRequest,
    DatasetProject,
    DatasetReviewRequest,
    DriftReport,
    DriftRequest,
    QualityStore,
    ReleaseActionRequest,
    ReleaseCreateRequest,
    ReleaseEvidence,
    ReleaseRecord,
    ReviewDecision,
    ReviewItem,
    SeedNote,
    SignificanceResult,
    TrajectoryRequest,
    apply_similarity,
    build_dataset,
    data_mix,
    evaluate_trajectory,
    production_drift,
    security_suite,
    shares_family,
    significance,
    slice_analysis,
)
from prompt_playoff.registry import Registry, RegistryError
from prompt_playoff.rubric import judge_rows
from prompt_playoff.service import PromptSelectorService, TechniqueNameConflict
from prompt_playoff.strategies import aggregator_names, strategy_names
from prompt_playoff.technique_examples import compiled_examples
from prompt_playoff.technique_store import to_yaml


@asynccontextmanager
async def lifespan(app: FastAPI):
    registry = Registry.load()
    app.state.service = PromptSelectorService(registry)
    app.state.jobs = JobStore()
    app.state.quality = QualityStore()
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


def _quality(request: Request) -> QualityStore:
    return request.app.state.quality


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
    #: The prompt as it was authored, when the caller is holding one. Sent so a
    #: measurement is of that prompt rather than of a fresh compile of the same
    #: technique, which drops whatever an engine model wrote into it. Omitted,
    #: the technique is compiled per example exactly as before. On `/v1/optimize`
    #: it is the baseline the search has to beat, for the same reason: a gain
    #: over a compile nobody has seen is not a gain over the prompt you have.
    prompt: CompiledProgram | None = None
    business_case_id: str | None = Field(default=None, min_length=1, max_length=160)


class BusinessCaseCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=4000)


class BusinessCaseUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=4000)
    archived: bool | None = None


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
    #: Search even when the number being maximised cannot tell a good answer
    #: from an answer to a different question. Refused by default, because such
    #: a search reliably raises the score and does not reliably improve the
    #: prompt; sending this says the result will be read as drift.
    allow_noisy_objective: bool = False

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


class TechniqueExportRequest(BaseModel):
    """`OptimizationResult.exported_technique`, on its way to a file or a store."""

    technique: dict[str, Any]
    #: A name of its own. The exporter defaults to `<recipe>.optimized`, which
    #: collides with the next winner from the same recipe; supply one when you
    #: intend to keep more than one.
    technique_id: str | None = Field(default=None, min_length=1, max_length=120)
    #: Keep it on this server, so its id resolves for runs and runtime exports.
    save: bool = False


class TechniqueImportRequest(BaseModel):
    """A technique file from another server, on its way into this one's store."""

    yaml: str = Field(min_length=1, max_length=200_000)
    technique_id: str | None = Field(default=None, min_length=1, max_length=120)


class DeploymentExportRequest(BaseModel):
    task: TaskProfile
    technique_id: str
    language: str = Field(pattern="^(python|typescript)$")
    response_schema: dict[str, Any] | None = None
    variables: dict[str, str] = Field(default_factory=dict)
    exemplars: list[Exemplar] = Field(default_factory=list)


class PairwiseJudgeRequest(BaseModel):
    input: str = Field(min_length=1, max_length=100_000)
    answer_a: str = Field(min_length=1, max_length=100_000)
    answer_b: str = Field(min_length=1, max_length=100_000)
    rubric: list[str] = Field(min_length=1, max_length=12)
    judge_model: ModelProfile
    #: Models that produced the answers being judged. Supplied so the answer can
    #: say when the judge is the same lineage as the thing it is scoring.
    subject_models: list[str] = Field(default_factory=list, max_length=8)
    seed: int = 20260816
    timeout_seconds: float = Field(default=120, gt=0, le=1800)


class RubricRunRequest(BaseModel):
    """Judge a whole recorded run against the reference answers its rows carry."""

    #: The rows, as `(id, input, answer, reference)` is assembled from them.
    dataset: str = Field(min_length=1, max_length=200)
    runs: list[dict[str, Any]] = Field(min_length=1, max_length=2000)
    rubric: list[str] = Field(min_length=1, max_length=12)
    judge_model: ModelProfile
    subject_models: list[str] = Field(default_factory=list, max_length=8)
    seed: int = 20260816
    timeout_seconds: float = Field(default=120, gt=0, le=1800)
    #: Judging every repeat of every row costs as many calls as the run itself
    #: did. One repeat per row is the default, because a judge asked the same
    #: question three times mostly answers it three times.
    repeat: int = Field(default=0, ge=0, le=9)


class PairwiseJudgeScores(BaseModel):
    #: The scale the judge is *asked* for: this bound is what its response
    #: schema advertises. Reading the reply back is deliberately more
    #: forgiving — see `PairwiseJudgeReading`.
    first: float = Field(ge=0, le=10)
    second: float = Field(ge=0, le=10)


class PairwiseJudgeOutput(BaseModel):
    winner: Literal["first", "second", "tie"]
    scores: PairwiseJudgeScores
    rationale: str


class PairwiseReadScores(BaseModel):
    #: No upper bound, because the number that arrives is in units nobody has
    #: established yet. `_judge_scale` establishes them.
    first: float = Field(ge=0)
    second: float = Field(ge=0)


class PairwiseJudgeReading(BaseModel):
    """A verdict as it arrived, before anyone knows which scale it is on.

    The schema handed to the judge says 0-10 and most of them comply, but a
    model that decided on 0-100 answered the question correctly and only
    disagreed about units. Validating the reply against the asked-for bound
    turned that into a 502 that spent a model call and returned nothing —
    deterministically, for the same input, so retrying never helped either.
    The reply is therefore read without an upper bound and normalised after.
    """

    winner: Literal["first", "second", "tie"]
    scores: PairwiseReadScores
    rationale: str


class StatisticsRequest(BaseModel):
    before: list[float] = Field(min_length=1, max_length=100_000)
    after: list[float] = Field(min_length=1, max_length=100_000)


class SliceAnalysisRequest(BaseModel):
    examples: list[BenchmarkExample] = Field(min_length=1)
    runs: list[dict[str, Any]] = Field(min_length=1)


class RegressionRequest(BaseModel):
    before_id: str
    after_id: str
    technique_id: str | None = None
    quality_tolerance: float = Field(default=0.01, ge=0, le=1)
    latency_tolerance: float = Field(default=0.1, ge=0)


class RegressionActionRequest(BaseModel):
    experiment_id: str


class ModelMatrixRequest(BenchmarkRequest):
    models: list[ModelProfile] = Field(min_length=2, max_length=8)


class ContextVariant(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    context: str = Field(max_length=200_000)


class ContextLabRequest(BenchmarkRequest):
    contexts: list[ContextVariant] = Field(min_length=2, max_length=8)


class SecurityEvaluationRequest(BenchmarkRequest):
    source: BenchmarkExample


# --------------------------------------------------------------------------- #
# static + introspection
# --------------------------------------------------------------------------- #


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index() -> HTMLResponse:
    body = files("prompt_playoff").joinpath("data/static/index.html").read_text(encoding="utf-8")
    return HTMLResponse(content=body, headers={"Cache-Control": "no-cache, must-revalidate"})


@app.get("/assets/{asset_name}", include_in_schema=False)
def static_asset(asset_name: str) -> Response:
    """Serve only the frontend's packaged, single-segment style, script, and image assets."""
    suffix = Path(asset_name).suffix
    media_types = {".css": "text/css", ".js": "text/javascript", ".webp": "image/webp"}
    if (
        asset_name != Path(asset_name).name
        or asset_name.startswith(".")
        or suffix not in media_types
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    resource = files("prompt_playoff").joinpath("data/static", asset_name)
    if not resource.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    # The asset names never change, so a browser that caches them shows an old
    # interface against a new server and gives no sign that it is doing so.
    # Revalidating on every load costs nothing here: the server is on the same
    # machine as the browser.
    return Response(
        content=resource.read_bytes(),
        media_type=media_types[suffix],
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


@app.get("/favicon.svg", include_in_schema=False)
def favicon() -> Response:
    body = files("prompt_playoff").joinpath("data/static/favicon.svg").read_text(encoding="utf-8")
    return Response(content=body, media_type="image/svg+xml")


@app.get("/help", response_class=HTMLResponse, include_in_schema=False)
def help_page() -> str:
    return files("prompt_playoff").joinpath("data/static/help.html").read_text(encoding="utf-8")


@app.get("/help/ru", response_class=HTMLResponse, include_in_schema=False)
def help_page_ru() -> str:
    return files("prompt_playoff").joinpath("data/static/help.ru.html").read_text(encoding="utf-8")


@app.get("/evaluation", response_class=HTMLResponse, include_in_schema=False)
def evaluation_page() -> str:
    return (
        files("prompt_playoff").joinpath("data/static/evaluation.html").read_text(encoding="utf-8")
    )


@app.get("/evaluation/ru", response_class=HTMLResponse, include_in_schema=False)
def evaluation_page_ru() -> str:
    return (
        files("prompt_playoff")
        .joinpath("data/static/evaluation.ru.html")
        .read_text(encoding="utf-8")
    )


@app.get("/llm-or-not", response_class=HTMLResponse, include_in_schema=False)
def llm_or_not_page() -> str:
    return (
        files("prompt_playoff").joinpath("data/static/llm-or-not.html").read_text(encoding="utf-8")
    )


@app.get("/llm-or-not/ru", response_class=HTMLResponse, include_in_schema=False)
def llm_or_not_page_ru() -> str:
    return (
        files("prompt_playoff")
        .joinpath("data/static/llm-or-not.ru.html")
        .read_text(encoding="utf-8")
    )


@app.get("/prompt-vs-finetuning", response_class=HTMLResponse, include_in_schema=False)
def prompt_vs_finetuning_page() -> str:
    return (
        files("prompt_playoff")
        .joinpath("data/static/prompt-vs-finetuning.html")
        .read_text(encoding="utf-8")
    )


@app.get("/prompt-vs-finetuning/ru", response_class=HTMLResponse, include_in_schema=False)
def prompt_vs_finetuning_page_ru() -> str:
    return (
        files("prompt_playoff")
        .joinpath("data/static/prompt-vs-finetuning.ru.html")
        .read_text(encoding="utf-8")
    )


# The guide used to be called Benchmarks and lived at these two paths. It is one
# document either way, so the old paths point at the new ones rather than
# serving a second copy that would drift from it.
@app.get("/benchmarks", include_in_schema=False)
def benchmarks_page() -> RedirectResponse:
    return RedirectResponse("/evaluation", status_code=301)


@app.get("/benchmarks/ru", include_in_schema=False)
def benchmarks_page_ru() -> RedirectResponse:
    return RedirectResponse("/evaluation/ru", status_code=301)


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
        #: How each grader's number gets misread, for the ones where the obvious
        #: reading is wrong. Served beside the help text so a report can print
        #: the warning next to the number instead of leaving a reader to
        #: discover on their own that word overlap does not mean correctness.
        "grader_caveats": GRADER_CAVEATS,
        #: Which graders score every answer 0 or 1. Their mean is a share of
        #: answers; every other mean is an average score, and a page that says
        #: "N in 100 were correct" over a partial-credit grader is inventing a
        #: pass rate nobody measured.
        "pass_rate_graders": sorted(PASS_RATE_GRADERS),
        #: Graders that score by comparing an answer with one reference answer.
        "reference_overlap_graders": sorted(REFERENCE_OVERLAP_GRADERS),
        #: How the graders become the two headline numbers. The Measurement
        #: screen names, before a run, which grader its quality will come from
        #: and which ones feed reliability — so both orderings are served from
        #: the module that applies them rather than copied into the page.
        "quality_preference": list(QUALITY_PREFERENCE),
        "reliability_graders": sorted(RELIABILITY_GRADERS),
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
    """Everything resolvable by id, saved optimization winners included.

    They are listed but never ranked: `/v1/recommend` sees the registry only,
    because a recipe tuned on one dataset is not evidence about anyone else's.
    """
    return sorted(_service(request).all_techniques.values(), key=lambda item: item.id)


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


@lru_cache(maxsize=1)
def _package_licence() -> str:
    """The licence the bundled rows ship under, read from the package itself.

    The sets built here are files inside this distribution and carry its
    licence; naming it in the page would be a second copy of pyproject that
    nothing keeps honest.
    """
    try:
        meta = metadata("prompt-playoff")
    except PackageNotFoundError:
        return ""
    return meta.get("License-Expression") or meta.get("License") or ""


def _provenance(name: str) -> dict[str, str] | None:
    """Whose rows a bundled set holds, and under what licence.

    The four sets sampled from public corpora are described by the import
    presets that fetched them, so the repository, the licence and the paper
    cannot drift from the code that did the fetching. Everything else that
    ships inside the package was built here and carries the package's licence.
    Sets a person brought — uploaded, imported, generated — are theirs, and this
    says nothing about them.
    """
    spec = HF_PRESETS.get(name) or HF_QA_PRESETS.get(name) or HF_CODE_PRESETS.get(name)
    if spec is not None:
        return {
            "source": spec.repo_id,
            "url": f"https://huggingface.co/datasets/{spec.repo_id}",
            "licence": spec.licence,
            "citation": spec.citation,
        }
    if name.startswith(("uploaded:", "hf:", "builder:", "business:")):
        return None
    return {"source": "built here", "licence": _package_licence()}


def _free_text_facts(examples: list[BenchmarkExample]) -> dict[str, Any]:
    """What word overlap can and cannot decide about these rows, before any run.

    Rows whose right answer is prose get scored by comparing words with that one
    reference, and on open-ended work that comparison has a floor: replies to
    unrelated tickets already share most of their wording. The floor is measured
    here, off the rows alone, so a set that cannot be scored this way says so on
    the library shelf — before someone spends an evening improving a prompt
    against a number that was never going to move.
    """
    references = overlap_scored_references(examples)
    return {
        "free_text": len(references),
        "token_f1_chance_level": token_f1_chance_level(references),
    }


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
                **_free_text_facts(examples),
                "tags": sorted({tag for item in examples for tag in item.tags}),
                "provenance": _provenance(name),
                # Whether this set survives a restart. Only a set the user
                # brought can fail to, and the library says which it is looking
                # at rather than leaving it to be discovered on the day.
                "kept": service.dataset_store.path_for(name).exists(),
            }
        )
    return entries


# Ahead of /v1/datasets/{name:path}, which would otherwise read "catalog" as the
# name of a set nobody has.
@app.get("/v1/datasets/catalog")
def dataset_catalog(request: Request) -> dict[str, Any]:
    """The business taxonomy and cases, joined to the sets this server can read.

    Every registered set is counted, not only the business ones: a taxonomy task
    may route to a packaged benchmark, and a route the count skipped would be
    reported as a gap. Counting means parsing each file, which this screen can
    afford — and a set that fails to parse is reported as absent rather than
    taking the whole catalogue down.
    """
    service = _service(request)
    available: dict[str, int] = {}
    for name in service.dataset_names:
        try:
            available[name] = len(service.dataset(name))
        except Exception:
            continue
    try:
        return catalog(available)
    except CatalogError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/v1/datasets/upload", status_code=status.HTTP_201_CREATED)
async def upload_dataset(
    request: Request,
    file: Annotated[UploadFile, File()],
    keep: Annotated[bool, Form()] = False,
) -> dict[str, Any]:
    """Validate a JSONL file and register it, optionally past this server's life.

    ``keep`` is off by default and asked for in the interface rather than
    assumed: these rows came off someone's own machine, and writing them next to
    the measurements is a promise to make on purpose. Off, the set behaves as it
    always has — usable now, gone on restart.
    """
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
    _service(request).add_user_dataset(name, examples, persist=keep)
    return {
        "name": name,
        "filename": file.filename,
        "examples": len(examples),
        "has_expected": sum(1 for item in examples if item.expected is not None),
        "has_schema": sum(1 for item in examples if item.response_schema is not None),
        **_free_text_facts(examples),
        "kept": keep,
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
        **_free_text_facts(examples),
        "skipped": len(rows) - len(examples),
        "saved_to": str(saved) if saved else None,
    }


class RequirementsRequest(BaseModel):
    #: What shape of work these rows hold, which is what decides which
    #: requirements can honestly be read off them.
    contract: Literal["reply", "summary", "draft"]


@app.post("/v1/datasets/{name:path}/requirements")
def derive_requirements(
    name: str, payload: RequirementsRequest, request: Request
) -> dict[str, Any]:
    """Give a set of prose rows the requirements a rule can decide.

    The rows arrive able to support one number — how many words an answer shares
    with the one reference it was given — and that number cannot say whether an
    answer is right. This reads the requirements off the rows themselves: the
    identifier a reply has to carry back, the unfilled placeholder that must not
    ship, the length the channel allows. Each is kept only where that row's own
    reference answer already meets it, so nothing written here can mark a model
    wrong for answering as well as the person did.

    Only a set the user brought in: a bundled set lives inside the installed
    package and already carries whatever contract its catalogue entry declares.
    """
    service = _service(request)
    if name not in service.user_datasets:
        raise HTTPException(
            status_code=404 if name not in service.dataset_names else 409,
            detail=(
                f"{name} is not a set you brought in. Bundled sets carry the contract their "
                "catalogue entry declares and are not edited here."
            ),
        )
    before = service.dataset(name)
    rows = apply_requirements([item.model_dump(mode="json") for item in before], payload.contract)
    examples = [BenchmarkExample.model_validate(row) for row in rows]
    kept = service.dataset_store.path_for(name).exists()
    service.add_user_dataset(name, examples, persist=kept)

    # The state the set is now in, not the difference this call made. Pressing
    # the button twice is a reasonable thing to do, and the second press used to
    # answer "nothing could be derived" about a set that was fully derived.
    carried = Counter(
        grader
        for item in examples
        for grader in item.graders
        if grader not in REFERENCE_OVERLAP_GRADERS
    )
    heads = Counter(headline_grader(item.graders) for item in examples)
    return {
        "name": name,
        "contract": payload.contract,
        "examples": len(examples),
        "requirements": dict(carried),
        "added": dict(
            Counter(
                grader
                for old, new in zip(before, examples, strict=True)
                for grader in set(new.graders) - set(old.graders)
            )
        ),
        #: How many rows still have nothing better than word overlap to answer
        #: for them. Reported rather than hidden: on some corpora the answer is
        #: most of them, and that is a fact about the rows, not a failure here.
        "still_overlap_scored": sum(
            count for grader, count in heads.items() if grader in REFERENCE_OVERLAP_GRADERS
        ),
        **_free_text_facts(examples),
    }


@app.delete("/v1/datasets/{name:path}")
def delete_dataset(name: str, request: Request) -> dict[str, Any]:
    """Remove a set the user brought in. Bundled sets are refused, not hidden.

    Deleting rows is not undoable, so the answer says exactly what went: the
    name, and the file that was unlinked if the set had one on disk.
    """
    service = _service(request)
    try:
        removed = service.remove_user_dataset(name)
    except KeyError as exc:
        if name in service.registry.datasets:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{name} is bundled with Prompt Playoff and cannot be deleted here. "
                    "Only sets you uploaded, imported or built can be removed."
                ),
            ) from exc
        raise HTTPException(status_code=404, detail=f"Unknown dataset: {name}") from exc
    return {"deleted": True, "name": name, "removed_file": str(removed) if removed else None}


# Ahead of the catch-all below, which would otherwise read "agents/mix" as a
# dataset name and answer 404 for a set that exists.
@app.get("/v1/datasets/{name:path}/mix", response_model=DataMix)
def dataset_mix(name: str, request: Request) -> DataMix:
    """How much of a named set a model wrote, for the scorecard to say so."""
    try:
        return data_mix(_service(request).dataset(name))
    except RegistryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# `:path` because an imported Hub dataset is named after its repo, and a repo id
# carries a slash. Declared after the /hub/ routes, which therefore still win.
@app.get("/v1/datasets/{name:path}", response_model=list[BenchmarkExample])
def dataset_examples(name: str, request: Request) -> list[BenchmarkExample]:
    try:
        return _service(request).dataset(name)
    except RegistryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# --------------------------------------------------------------------------- #
# dataset builder + review-safe synthetic data
# --------------------------------------------------------------------------- #

#: The seed inputs only. Answers are a second phase, because an answer sampled
#: once alongside the question it belongs to cannot be checked against anything.
_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "examples": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "input": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["input", "tags"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["examples"],
    "additionalProperties": False,
}

_ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}


def _generator_prompt(
    payload: DatasetBuildRequest, persona: str | None, sample: int
) -> CompiledPrompt:
    voice = (
        f"Write every input as {persona} would type it — their vocabulary, their "
        "length, and what they leave unsaid.\n"
        if persona
        else ""
    )
    return CompiledPrompt(
        technique_id="dataset-builder",
        stage="generate",
        messages=[
            Message(
                role="system",
                content=(
                    "Write evaluation inputs, not answers. Cover normal, boundary, malformed, "
                    "long-context and adversarial cases, and make the hard ones genuinely hard "
                    "rather than long. Return the requested JSON.\n" + voice
                ),
            ),
            Message(
                role="user",
                content=f"Write {payload.count} inputs for this task:\n{payload.description}",
            ),
        ],
        response_schema=_INPUT_SCHEMA,
        # One sample is one voice; several samples are only worth drawing if they
        # are allowed to diverge, so the temperature rises with the sample count.
        generation_options={"temperature": 0.4 if payload.candidates == 1 else 0.8, "top_p": 0.95}
        | ({"seed": payload.seed + sample} if payload.candidates > 1 else {}),
    )


async def _sampled_inputs(
    service: PromptSelectorService, payload: DatasetBuildRequest
) -> list[tuple[str, list[str], str | None]]:
    """Seed inputs pooled from ``candidates`` independent samples, deduplicated.

    Taken round-robin rather than sample by sample: one sample's list would
    otherwise fill the whole set and the other calls would be paid for nothing.
    """
    model = payload.generator_model
    assert model is not None
    provider = service.provider(
        TaskProfile(task_type=TaskType.summarization, model=model), phase="dataset-builder"
    )
    personas = PERSONAS if payload.personas else (None,)
    lists: list[list[tuple[str, list[str], str | None]]] = []
    for sample in range(payload.candidates):
        persona = personas[sample % len(personas)]
        generated = await provider.generate(_generator_prompt(payload, persona, sample), model)
        rows = json.loads(generated.content).get("examples", [])
        lists.append(
            [
                (row["input"], list(row.get("tags", [])), persona)
                for row in rows
                if isinstance(row, dict) and str(row.get("input", "")).strip()
            ]
        )
    pooled: list[tuple[str, list[str], str | None]] = []
    seen: set[str] = set()
    for index in range(max((len(item) for item in lists), default=0)):
        for rows in lists:
            if index >= len(rows):
                continue
            key = re.sub(r"\s+", " ", rows[index][0]).strip().casefold()
            if key in seen:
                continue
            seen.add(key)
            pooled.append(rows[index])
    return pooled[: payload.count]


async def _agreed_answer(
    service: PromptSelectorService, payload: DatasetBuildRequest, text: str
) -> tuple[str | None, float | None]:
    """Sample an answer ``candidates`` times; keep the modal one and its share.

    The share is the reason this exists. It is not a quality score — it is how
    much the generator agreed with itself, which is what sorts the review queue.
    """
    model = payload.generator_model
    assert model is not None
    provider = service.provider(
        TaskProfile(task_type=TaskType.summarization, model=model), phase="dataset-builder"
    )
    answers: list[str] = []
    for sample in range(payload.candidates):
        prompt = CompiledPrompt(
            technique_id="dataset-builder",
            stage="answer",
            messages=[
                Message(
                    role="system",
                    content=(
                        "Answer the input exactly as the task requires. Be brief and literal. "
                        "This answer is a proposal a person will check."
                    ),
                ),
                Message(role="user", content=f"TASK:\n{payload.description}\n\nINPUT:\n{text}"),
            ],
            response_schema=_ANSWER_SCHEMA,
            generation_options={"temperature": 0.8, "top_p": 0.95, "seed": payload.seed + sample},
        )
        result = await provider.generate(prompt, model)
        answer = str(json.loads(result.content).get("answer", "")).strip()
        if answer:
            answers.append(answer)
    if not answers:
        return None, None
    grouped: dict[str, list[str]] = {}
    for answer in answers:
        grouped.setdefault(re.sub(r"\s+", " ", answer).strip().casefold(), []).append(answer)
    modal = max(grouped.values(), key=len)
    return modal[0], round(len(modal) / payload.candidates, 4)


async def _generated_seeds(
    service: PromptSelectorService, payload: DatasetBuildRequest
) -> tuple[list[BenchmarkExample], dict[str, SeedNote]]:
    model = payload.generator_model
    assert model is not None
    pooled = await _sampled_inputs(service, payload)
    if not pooled:
        raise ValueError("Generator returned no usable inputs")
    examples: list[BenchmarkExample] = []
    notes: dict[str, SeedNote] = {}
    for index, (text, tags, persona) in enumerate(pooled, 1):
        answer, agreement = (None, None)
        if payload.propose_answers:
            answer, agreement = await _agreed_answer(service, payload, text)
        seed_id = f"model-seed-{index:03d}"
        examples.append(
            BenchmarkExample(
                id=seed_id,
                input=text,
                expected=answer,
                tags=[*tags, "model-generated"],
            )
        )
        notes[seed_id] = SeedNote(generator=model.model_id, persona=persona, agreement=agreement)
    return examples, notes


@app.get("/v1/dataset-projects", response_model=list[DatasetProject])
def dataset_projects(request: Request) -> list[DatasetProject]:
    return _quality(request).datasets()


@app.post(
    "/v1/dataset-projects", response_model=DatasetProject, status_code=status.HTTP_201_CREATED
)
async def create_dataset_project(payload: DatasetBuildRequest, request: Request) -> DatasetProject:
    if payload.mode == "traces" and not payload.examples:
        try:
            rows = await asyncio.to_thread(
                import_langfuse_dataset,
                limit=payload.count,
                session_id=payload.trace_session_id,
                user_id=payload.trace_user_id,
                tags=payload.trace_tags or None,
                include_output_as_expected=False,
            )
            examples = [BenchmarkExample.model_validate(item) for item in rows]
            if not examples:
                raise ValueError("No matching Langfuse generations were found")
            payload = payload.model_copy(update={"examples": examples, "count": len(examples)})
        except (ImportError, RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=502, detail=f"Trace import failed: {exc}") from exc
    if payload.mode == "failures" and not payload.examples:
        raise HTTPException(
            status_code=422,
            detail=(
                "Building from failures needs the examples the prompt failed on. "
                "Run a benchmark first, then build from its report."
            ),
        )
    if payload.generator_model is not None and not payload.examples:
        try:
            examples, notes = await _generated_seeds(_service(request), payload)
            payload = payload.model_copy(
                update={"examples": examples, "count": len(examples), "seed_notes": notes}
            )
        except (ProviderError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            raise HTTPException(
                status_code=502, detail=f"Dataset generation failed: {exc}"
            ) from exc
    project = build_dataset(payload)
    # The one model call in this endpoint that cannot invent anything: it turns
    # the rows into vectors and says which of them are the same row reworded.
    # A failure here loses the two numbers, never the set — the rows are already
    # built, and refusing to hand them over because a check could not run would
    # throw away work the deterministic rules already verified.
    if payload.similarity_model is not None and len(project.examples) > 1:
        try:
            vectors = await embed_texts(
                payload.similarity_model,
                [item.example.input for item in project.examples],
            )
            project.diversity = apply_similarity(
                project.examples, vectors, payload.similarity_threshold
            )
            project.similarity_model = payload.similarity_model.model_id
        except ProviderError as exc:
            project.similarity_model = f"unavailable: {exc}"
    project = _quality(request).add_dataset(project)
    _quality(request).add_review(
        ReviewItem(
            id=f"review_{project.id}",
            kind="dataset",
            created_at=project.created_at,
            title=f"Review generated dataset: {project.name}",
            payload={
                "project_id": project.id,
                "examples": len(project.examples),
                # What a reviewer needs before opening the set: how much of it a
                # rule already objected to, and who wrote it.
                "flagged": sum(1 for item in project.examples if item.checks),
                "generator": project.generator,
            },
        )
    )
    return project


@app.post("/v1/dataset-projects/{project_id}/review", response_model=DatasetProject)
def review_dataset_project(
    project_id: str, payload: DatasetReviewRequest, request: Request
) -> DatasetProject:
    try:
        return _quality(request).review_dataset(project_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/dataset-projects/{project_id}/publish", status_code=status.HTTP_201_CREATED)
def publish_dataset_project(project_id: str, request: Request) -> dict[str, Any]:
    project = next((item for item in _quality(request).datasets() if item.id == project_id), None)
    if project is None:
        raise HTTPException(status_code=404, detail="Unknown dataset project")
    examples = project.approved_examples
    if not examples:
        raise HTTPException(
            status_code=422, detail="Approve at least one example before publishing"
        )
    name = f"builder:{project.name}"
    path = _service(request).add_user_dataset(name, examples, persist=True)
    return {"name": name, "examples": len(examples), "saved_to": str(path)}


@app.post("/v1/datasets/security-suite", response_model=list[BenchmarkExample])
def build_security_suite(example: BenchmarkExample) -> list[BenchmarkExample]:
    return security_suite(example)


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


@app.post("/v1/optimize/adopt", response_model=CompiledProgram)
def adopt_optimized(payload: AdoptOptimizedRequest, request: Request) -> CompiledProgram:
    """Turn an optimization winner into the prompt the workspace is holding."""
    try:
        return _service(request).adopt_optimized(payload)
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


def _business_case_for(
    service: PromptSelectorService, case_id: str | None
) -> BusinessCaseRecord | None:
    if case_id is None:
        return None
    record = service.business_cases.get(case_id)
    if record is None:
        raise HTTPException(status_code=422, detail="Unknown business case")
    if record.archived:
        raise HTTPException(status_code=422, detail="This business case is archived")
    return record


@app.get("/v1/business-cases", response_model=list[BusinessCaseRecord])
def list_business_cases(
    request: Request, include_archived: bool = False
) -> list[BusinessCaseRecord]:
    return _service(request).business_cases.list(include_archived=include_archived)


@app.post(
    "/v1/business-cases",
    response_model=BusinessCaseRecord,
    status_code=status.HTTP_201_CREATED,
)
def create_business_case(
    payload: BusinessCaseCreateRequest, request: Request
) -> BusinessCaseRecord:
    try:
        return _service(request).business_cases.create(payload.name, payload.description)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.patch("/v1/business-cases/{case_id}", response_model=BusinessCaseRecord)
def update_business_case(
    case_id: str, payload: BusinessCaseUpdateRequest, request: Request
) -> BusinessCaseRecord:
    if payload.name is None and payload.description is None and payload.archived is None:
        raise HTTPException(status_code=422, detail="Provide a field to update")
    try:
        return _service(request).business_cases.update(
            case_id,
            name=payload.name,
            description=payload.description,
            archived=payload.archived,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown business case") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.delete("/v1/business-cases/{case_id}", response_model=BusinessCaseRecord)
def archive_business_case(case_id: str, request: Request) -> BusinessCaseRecord:
    """Archive rather than erase: recorded experiment lineage must stay resolvable."""
    try:
        return _service(request).business_cases.update(case_id, archived=True)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown business case") from exc


@app.post("/v1/benchmark", response_model=Job)
async def start_benchmark(payload: BenchmarkRequest, request: Request) -> Job:
    service, store = _service(request), _jobs(request)
    business_case = _business_case_for(service, payload.business_case_id)
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
            prompt=payload.prompt,
            business_case=business_case,
        )
        return report.model_dump(mode="json")

    return store.start(job, work)


@app.post("/v1/compare", response_model=Job)
async def start_compare(payload: CompareRequest, request: Request) -> Job:
    service, store = _service(request), _jobs(request)
    business_case = _business_case_for(service, payload.business_case_id)
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
            prompt=payload.prompt,
            business_case=business_case,
        )
        return {
            "comparison": comparison.model_dump(mode="json"),
            "reports": [item.model_dump(mode="json") for item in reports],
        }

    return store.start(job, work)


@app.post("/v1/optimize", response_model=Job)
async def start_optimize(payload: OptimizeRequest, request: Request) -> Job:
    service, store = _service(request), _jobs(request)
    business_case = _business_case_for(service, payload.business_case_id)
    if payload.backend not in BACKENDS:
        raise HTTPException(
            status_code=422, detail=f"Unknown backend. Known: {', '.join(BACKENDS)}"
        )
    # Refused here rather than inside the job, so it arrives as an answer to the
    # click instead of as a failed run — and carries a code, so the screen can
    # offer to override it without matching on the wording of a sentence.
    try:
        examples, _ = service.resolve_dataset(payload.dataset, payload.examples or None)
        refuse_unmeasurable(examples, allowed=payload.allow_noisy_objective)
    except UnmeasurableObjective as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "unmeasurable_objective",
                "message": str(exc),
                "chance_level": token_f1_chance_level(overlap_scored_references(examples)),
            },
        ) from exc
    except (ValueError, RegistryError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
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
            prompt=payload.prompt,
            business_case=business_case,
            allow_noisy_objective=payload.allow_noisy_objective,
        )
        return result.model_dump(mode="json")

    return store.start(job, work)


@app.get("/v1/experiments", response_model=list[ExperimentRecord])
def list_experiments(request: Request) -> list[ExperimentRecord]:
    return _service(request).experiments.list()


@app.get("/v1/experiments.csv")
def download_experiments_csv(request: Request) -> Response:
    """The history as a spreadsheet: Excel and Numbers open it, Sheets imports it."""
    body = experiments_csv(_service(request).experiments.list())
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="prompt-playoff-history.csv"',
        },
    )


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


# --------------------------------------------------------------------------- #
# judge, analysis, regressions, matrices, context, and production lifecycle
# --------------------------------------------------------------------------- #


def _family_warning(judge: str, subjects: list[str]) -> str | None:
    """The one thing blinding cannot hide: a judge preferring its own lineage."""
    same = [item for item in subjects if shares_family(judge, item)]
    if not same:
        return None
    return (
        f"{judge} is judging answers from {', '.join(sorted(set(same)))} — the same model "
        "family. A judge tends to score text from its own lineage higher, so treat this "
        "verdict as weaker evidence than a benchmark score, and prefer a judge from "
        "another family."
    )


def _judge_leakage(payload: PairwiseJudgeRequest) -> str | None:
    return _family_warning(payload.judge_model.model_id, payload.subject_models)


def _judge_scale(first: float, second: float) -> float:
    """Which scale a judge answered on, named by the larger of its two scores.

    The smaller score can legitimately be 0 on every scale, so it distinguishes
    nothing; the larger one is what separates 0-1 from 0-10 from 0-100.
    """
    top = max(first, second)
    if top > 10:
        return 100.0
    return 10.0 if top > 1 else 1.0


@app.post("/v1/evaluate/rubric")
async def rubric_run(payload: RubricRunRequest, request: Request) -> dict[str, Any]:
    """Blind rubric judging across a whole run, not one pair at a time.

    The question a person has about a drafting prompt is whether it writes well
    across the set, and the tool could previously only settle an argument about
    one example. Every row is compared with the reference answer it already
    carries, order hidden, and the result is a win rate against the person who
    wrote those references.

    It stays a model's opinion: one review item for the batch, and no route into
    a benchmark number or a CI gate. What CI enforces is still only what a rule
    decided.
    """
    service = _service(request)
    try:
        examples = {item.id: item for item in service.dataset(payload.dataset)}
    except (KeyError, RegistryError, OSError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=f"Unknown dataset: {exc}") from exc

    rows: list[tuple[str, str, str, str]] = []
    for item in payload.runs:
        try:
            run = ExampleRun.model_validate(item)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=f"Unreadable run row: {exc}") from exc
        example = examples.get(run.example_id)
        if run.repeat != payload.repeat or example is None or run.error or not run.output.strip():
            continue
        reference = example.expected
        if not isinstance(reference, str) or not reference.strip():
            continue
        rows.append((run.example_id, example.input, run.output, reference))
    if not rows:
        raise HTTPException(
            status_code=422,
            detail=(
                "No row could be judged: a row needs an answer from the run and a written "
                "reference answer in the dataset. Rows whose expected answer is a structure "
                "are graded by rule, not judged."
            ),
        )

    provider = service.provider(
        TaskProfile(task_type=TaskType.summarization, model=payload.judge_model), phase="judge"
    )
    verdict = await judge_rows(
        rows,
        rubric=payload.rubric,
        judge_model=payload.judge_model,
        generate=provider.generate,
        seed=payload.seed,
        timeout_seconds=payload.timeout_seconds,
        self_preference_warning=_family_warning(
            payload.judge_model.model_id, payload.subject_models
        ),
    )
    body = verdict.model_dump(mode="json") | {
        "dataset": payload.dataset,
        "summary": verdict.summary,
    }
    review = _quality(request).add_review(
        ReviewItem(
            id=f"review_{uuid.uuid4().hex[:12]}",
            kind="judge",
            created_at=datetime.now(UTC).isoformat(timespec="seconds"),
            title=f"Confirm rubric verdict on {payload.dataset}",
            payload=body,
        )
    )
    return {**body, "review_id": review.id}


@app.post("/v1/evaluate/pairwise")
async def pairwise_judge(payload: PairwiseJudgeRequest, request: Request) -> dict[str, Any]:
    """Blind pairwise judging with seeded order randomisation and human review."""
    rng = random.Random(payload.seed)
    order = ["a", "b"]
    rng.shuffle(order)
    answers = {"a": payload.answer_a, "b": payload.answer_b}
    schema = PairwiseJudgeOutput.model_json_schema()
    prompt = CompiledPrompt(
        technique_id="pairwise-judge",
        stage="judge",
        messages=[
            Message(
                role="system",
                content=(
                    "You are an impartial evaluator. Apply only the rubric. Do not infer which "
                    "answer is a baseline or candidate. Score each answer from 0 to 10, where "
                    "10 fully satisfies the rubric. Return the requested JSON."
                ),
            ),
            Message(
                role="user",
                content=(
                    f"INPUT:\n{payload.input}\n\nRUBRIC:\n- "
                    + "\n- ".join(payload.rubric)
                    + f"\n\nFIRST ANSWER:\n{answers[order[0]]}"
                    + f"\n\nSECOND ANSWER:\n{answers[order[1]]}"
                ),
            ),
        ],
        response_schema=schema,
        generation_options={"temperature": 0},
    )
    try:
        result = (
            await _service(request)
            .provider(
                TaskProfile(task_type=TaskType.summarization, model=payload.judge_model),
                phase="judge",
            )
            .generate(prompt, payload.judge_model, payload.timeout_seconds)
        )
        judged = PairwiseJudgeReading.model_validate_json(result.content)
    except (ProviderError, ValidationError, TypeError, KeyError) as exc:
        raise HTTPException(
            status_code=502, detail=f"Judge did not return valid JSON: {exc}"
        ) from exc
    winner = judged.winner
    mapped = "tie" if winner == "tie" else order[0 if winner == "first" else 1]
    raw_scores = {"first": judged.scores.first, "second": judged.scores.second}
    scale = _judge_scale(raw_scores["first"], raw_scores["second"])
    # A score above the top of its own scale is not a reading anyone can use;
    # it is capped rather than reported as more than whole.
    on_unit = {key: min(value / scale, 1.0) for key, value in raw_scores.items()}
    response = {
        "winner": mapped,
        "scores": {
            order[0]: round(on_unit["first"], 4),
            order[1]: round(on_unit["second"], 4),
        },
        "rationale": judged.rationale,
        "blind_order": order,
        "judge_model": payload.judge_model.model_id,
        "status": "pending_human_review",
        # Blinding hides which answer is which; it cannot hide that a model
        # tends to prefer text from its own lineage. That is the one thing this
        # verdict cannot notice about itself, so it is recorded next to it.
        "self_preference_warning": _judge_leakage(payload),
    }
    review = _quality(request).add_review(
        ReviewItem(
            id=f"review_{uuid.uuid4().hex[:12]}",
            kind="judge",
            created_at=datetime.now(UTC).isoformat(timespec="seconds"),
            title="Confirm pairwise judge decision",
            payload=response,
        )
    )
    return {**response, "review_id": review.id}


@app.post("/v1/analysis/statistics", response_model=SignificanceResult)
def analyze_statistics(payload: StatisticsRequest) -> SignificanceResult:
    try:
        return significance(payload.before, payload.after)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/analysis/slices")
def analyze_slices(payload: SliceAnalysisRequest) -> list[dict[str, Any]]:
    try:
        runs = [ExampleRun.model_validate(item) for item in payload.runs]
        return [item.model_dump(mode="json") for item in slice_analysis(payload.examples, runs)]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/regressions/analyze")
def analyze_regression(payload: RegressionRequest, request: Request) -> dict[str, Any]:
    try:
        comparison = _service(request).experiments.compare(
            payload.before_id, payload.after_id, payload.technique_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    active = []
    for delta in comparison.deltas:
        if delta.delta is None:
            continue
        if delta.metric in {"quality", "reliability"} and delta.delta < -payload.quality_tolerance:
            active.append(delta.model_dump(mode="json"))
        if "latency" in delta.metric and delta.delta > payload.latency_tolerance:
            active.append(delta.model_dump(mode="json"))
    result = {
        "status": "failed" if active else "passed",
        "active": active,
        "comparison": comparison.model_dump(mode="json"),
        "actions": ["rerun", "accept_baseline"] if active else [],
    }
    if active:
        review = _quality(request).add_review(
            ReviewItem(
                id=f"review_{uuid.uuid4().hex[:12]}",
                kind="regression",
                created_at=datetime.now(UTC).isoformat(timespec="seconds"),
                title=f"Regression in {comparison.technique_id}",
                payload=result,
            )
        )
        result["review_id"] = review.id
    return result


@app.get("/v1/regressions/baselines")
def regression_baselines(request: Request) -> dict[str, str]:
    return _quality(request).baselines()


@app.post("/v1/regressions/accept-baseline")
def accept_regression_baseline(
    payload: RegressionActionRequest, request: Request
) -> dict[str, str]:
    record = _service(request).experiments.get(payload.experiment_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Unknown experiment")
    key = f"{record.provider}:{record.model_id}:{record.dataset}"
    return _quality(request).accept_baseline(key, record.id)


@app.post("/v1/regressions/rerun", response_model=Job)
async def rerun_regression(payload: RegressionActionRequest, request: Request) -> Job:
    service, store = _service(request), _jobs(request)
    record = service.experiments.get(payload.experiment_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Unknown experiment")
    if record.task is None or not record.technique_ids:
        raise HTTPException(
            status_code=422,
            detail="This older experiment lacks the reproducibility snapshot required to rerun it",
        )
    task = TaskProfile.model_validate(record.task)
    business_case = (
        service.business_cases.get(record.business_case_id) if record.business_case_id else None
    )
    job = store.create("regression-rerun")

    async def work() -> dict[str, Any]:
        report = await service.benchmark(
            task=task,
            technique_id=record.technique_ids[0],
            dataset_name=record.dataset,
            repeats=1,
            record=True,
            progress=lambda event: store.note(job.id, event),
            business_case=business_case,
        )
        return report.model_dump(mode="json")

    return store.start(job, work)


@app.post("/v1/model-matrix", response_model=Job)
async def start_model_matrix(payload: ModelMatrixRequest, request: Request) -> Job:
    service, store = _service(request), _jobs(request)
    business_case = _business_case_for(service, payload.business_case_id)
    job = store.create("model-matrix")

    async def work() -> dict[str, Any]:
        reports = []
        for model in payload.models:
            task = payload.task.model_copy(update={"model": model})
            model_id = model.model_id
            report = await service.benchmark(
                task=task,
                technique_id=payload.technique_id,
                dataset_name=payload.dataset,
                inline=payload.examples or None,
                repeats=payload.repeats,
                timeout_seconds=payload.timeout_seconds,
                record=payload.record,
                progress=lambda event, current_model_id=model_id: store.note(
                    job.id, {**event, "model_id": current_model_id}
                ),
                business_case=business_case,
            )
            reports.append(report.model_dump(mode="json"))
        winner = max(reports, key=lambda item: item["scorecard"]["quality"])
        return {"reports": reports, "winner_model": winner["model_id"]}

    return store.start(job, work)


@app.post("/v1/security-evaluate", response_model=Job)
async def start_security_evaluation(payload: SecurityEvaluationRequest, request: Request) -> Job:
    service, store = _service(request), _jobs(request)
    business_case = _business_case_for(service, payload.business_case_id)
    job = store.create("security-evaluation")

    async def work() -> dict[str, Any]:
        report = await service.benchmark(
            task=payload.task,
            technique_id=payload.technique_id,
            inline=security_suite(payload.source),
            repeats=payload.repeats,
            timeout_seconds=payload.timeout_seconds,
            record=payload.record,
            progress=lambda event: store.note(job.id, event),
            business_case=business_case,
        )
        return report.model_dump(mode="json")

    return store.start(job, work)


@app.post("/v1/context-lab", response_model=Job)
async def start_context_lab(payload: ContextLabRequest, request: Request) -> Job:
    service, store = _service(request), _jobs(request)
    examples, dataset_name = service.resolve_dataset(payload.dataset, payload.examples or None)
    job = store.create("context-lab")

    async def work() -> dict[str, Any]:
        reports = []
        for variant in payload.contexts:
            context_name = variant.name
            contextual = [
                item.model_copy(
                    update={"input": f"CONTEXT:\n{variant.context}\n\nINPUT:\n{item.input}"}
                )
                for item in examples
            ]
            report = await service.benchmark(
                task=payload.task,
                technique_id=payload.technique_id,
                inline=contextual,
                repeats=payload.repeats,
                timeout_seconds=payload.timeout_seconds,
                record=False,
                progress=lambda event, current_context=context_name: store.note(
                    job.id, {**event, "context": current_context}
                ),
            )
            reports.append({"context": variant.name, "report": report.model_dump(mode="json")})
        winner = max(reports, key=lambda item: item["report"]["scorecard"]["quality"])
        return {"dataset": dataset_name, "reports": reports, "winner_context": winner["context"]}

    return store.start(job, work)


@app.get("/v1/reviews", response_model=list[ReviewItem])
def list_reviews(request: Request) -> list[ReviewItem]:
    return _quality(request).reviews()


@app.post("/v1/reviews/{review_id}", response_model=ReviewItem)
def decide_review(review_id: str, payload: ReviewDecision, request: Request) -> ReviewItem:
    try:
        return _quality(request).decide_review(review_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/v1/releases", response_model=list[ReleaseRecord])
def list_releases(request: Request) -> list[ReleaseRecord]:
    return _quality(request).releases()


def _release_evidence(payload: ReleaseCreateRequest, request: Request) -> ReleaseEvidence:
    """Whether the cited run actually measured the prompt being frozen.

    The citation used to be taken on trust: any experiment id was accepted
    beside any prompt, and a release that measured one text and shipped another
    was indistinguishable from an honest one. The run records the fingerprint of
    what it measured, so the claim is now checked rather than believed.
    """
    if not payload.experiment_id:
        return "unverified"
    record = _service(request).experiments.get(payload.experiment_id)
    if record is None or record.authored_hash is None:
        return "indirect"
    return "measured" if record.authored_hash == prompt_fingerprint(payload.prompt) else "indirect"


@app.post("/v1/releases", response_model=ReleaseRecord, status_code=status.HTTP_201_CREATED)
def create_release(payload: ReleaseCreateRequest, request: Request) -> ReleaseRecord:
    """Register a prompt version against the run that measured it.

    Registering used to also raise a review item asking the same person, at the
    same keyboard, to approve what they had just registered — and advancing the
    release was then refused until they did. One user cannot be two, so the
    click proved nothing and the queue's own guide already said approving there
    "does not promote a release". The bar that decides is the committed one in
    `prompt-playoff.yaml`, applied to the cited run.
    """
    return _quality(request).create_release(payload, _release_evidence(payload, request))


def _release_gate(release: ReleaseRecord, request: Request) -> ReleaseGate:
    """The committed thresholds, applied to the run this release cites."""
    record = (
        _service(request).experiments.get(release.experiment_id) if release.experiment_id else None
    )
    metrics = None
    grades: dict[str, float] = {}
    quality_grader: str | None = None
    if record is not None:
        snapshot = record.metrics.get(record.winner or "") or next(
            iter(record.metrics.values()), None
        )
        if snapshot is not None:
            metrics = {
                name: float(value)
                for name, value in snapshot.model_dump().items()
                if isinstance(value, int | float)
            }
            grades = dict(snapshot.grades)
            quality_grader = snapshot.quality_grader
    return release_gate(
        release.technique_id,
        metrics,
        evidence=release.evidence,
        dataset_changed=_dataset_moved(record, request),
        grades=grades,
        quality_grader=quality_grader,
    )


def _dataset_moved(record: ExperimentRecord | None, request: Request) -> bool:
    """Have the rows this run was measured on changed since?

    Only answerable when the run recorded a revision and the set is still one
    this server can read; a set that has since been deleted is not evidence that
    it changed, so an unanswerable question is not treated as a yes.
    """
    if record is None or not record.dataset_revision:
        return False
    try:
        examples = _service(request).dataset(record.dataset)
    except (KeyError, RegistryError, OSError, ValueError):
        return False
    return dataset_revision(examples) != record.dataset_revision


@app.get("/v1/releases/{release_id}/gate", response_model=ReleaseGate)
def read_release_gate(release_id: str, request: Request) -> ReleaseGate:
    """What approving this release would be measured against, before you click."""
    release = next((item for item in _quality(request).releases() if item.id == release_id), None)
    if release is None:
        raise HTTPException(status_code=404, detail="Unknown release")
    return _release_gate(release, request)


class ReleaseCiteRequest(BaseModel):
    experiment_id: str = Field(min_length=1, max_length=64)


@app.post("/v1/releases/{release_id}/cite", response_model=ReleaseRecord)
def cite_release(release_id: str, payload: ReleaseCiteRequest, request: Request) -> ReleaseRecord:
    """Name the run behind a release that was registered without one."""
    quality = _quality(request)
    release = next((item for item in quality.releases() if item.id == release_id), None)
    if release is None:
        raise HTTPException(status_code=404, detail="Unknown release")
    record = _service(request).experiments.get(payload.experiment_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Unknown run")
    evidence: ReleaseEvidence = (
        "measured"
        if record.authored_hash and record.authored_hash == prompt_fingerprint(release.prompt)
        else "indirect"
    )
    try:
        return quality.cite_release(release_id, payload.experiment_id, evidence)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/v1/releases/{release_id}/manifest", response_model=ReleaseManifest)
def read_release_manifest(release_id: str, request: Request) -> ReleaseManifest:
    """The release as two files to commit, rather than a row kept in here.

    A register that lives in one person's SQLite is not a system of record: no
    colleague, no CI job and no future checkout can read it. The manifest hands
    the provenance to the repository, and the checks file hands the bar to
    `prompt-playoff check`, which is what actually guards anything.
    """
    release = next((item for item in _quality(request).releases() if item.id == release_id), None)
    if release is None:
        raise HTTPException(status_code=404, detail="Unknown release")
    record = (
        _service(request).experiments.get(release.experiment_id) if release.experiment_id else None
    )
    return release_manifest(
        release=release.model_dump(),
        gate=_release_gate(release, request).model_dump(),
        experiment=record.model_dump() if record is not None else None,
        dataset_changed=_dataset_moved(record, request),
        prompt_text=_release_prompt_text(release.prompt),
    )


def _release_prompt_text(prompt: dict[str, Any]) -> str:
    """The frozen text, however the screen that registered it shaped the payload.

    The workbench registers a compiled program — stages, each with its messages —
    and that shape fell through every branch here to the JSON dump at the end. So
    the manifest a repository committed as `prompt.text` was a serialized object
    rather than the prompt, and the one file meant to carry the exact wording out
    of this tool carried it in the least readable form the tool can produce.
    """
    for key in ("text", "prompt", "content"):
        value = prompt.get(key)
        if isinstance(value, str) and value.strip():
            return value
    stages = prompt.get("stages")
    if isinstance(stages, list):
        multi = len(stages) > 1
        parts = []
        for index, stage in enumerate(stages):
            if not isinstance(stage, dict):
                continue
            name = stage.get("stage") or f"stage {index + 1}"
            for message in stage.get("messages") or []:
                if not isinstance(message, dict):
                    continue
                role = str(message.get("role", "user")).upper()
                head = f"{name} · {role}" if multi else role
                parts.append(f"{head}\n{message.get('content', '')}")
        if parts:
            return "\n\n".join(parts)
    messages = prompt.get("messages")
    if isinstance(messages, list):
        parts = [
            f"{item.get('role', 'user')}: {item.get('content', '')}"
            for item in messages
            if isinstance(item, dict)
        ]
        if parts:
            return "\n\n".join(parts)
    return json.dumps(prompt, indent=2, ensure_ascii=False)


@app.post("/v1/releases/{release_id}/action", response_model=ReleaseRecord)
def act_on_release(
    release_id: str, payload: ReleaseActionRequest, request: Request
) -> ReleaseRecord:
    if payload.action == "approve":
        release = next(
            (item for item in _quality(request).releases() if item.id == release_id), None
        )
        if release is None:
            raise HTTPException(status_code=404, detail="Unknown release")
        # The committed thresholds are the whole gate. They are the numbers CI
        # enforces on the same prompt, so a release that clears them here clears
        # them there — which a second click by the same person never established.
        threshold_gate = _release_gate(release, request)
        if threshold_gate.blocks_approval:
            raise HTTPException(status_code=409, detail=threshold_gate.reason)
    try:
        return _quality(request).act_on_release(release_id, payload.action)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/drift", response_model=DriftReport)
def analyze_drift(payload: DriftRequest) -> DriftReport:
    return production_drift(payload)


@app.post("/v1/trajectories/evaluate")
def analyze_trajectory(payload: TrajectoryRequest) -> dict[str, Any]:
    return evaluate_trajectory(payload)


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


@app.post("/v1/export/technique")
def export_technique_file(payload: TechniqueExportRequest, request: Request) -> dict[str, Any]:
    """Turn an optimization winner into a technique file, and optionally keep it.

    Without `save` this is `optimize --export` over HTTP: the YAML comes back and
    the caller writes it wherever their registry lives. With `save`, the server
    also keeps it, which is what makes the winner resolvable by id — and so what
    makes `/v1/run` and the runtime export able to execute it at all.
    """
    service = _service(request)
    try:
        spec = TechniqueSpec.model_validate(
            {**payload.technique, **({"id": payload.technique_id} if payload.technique_id else {})}
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=422, detail=f"This is not a technique the optimizer produced: {exc}"
        ) from exc
    saved_to = None
    if payload.save:
        try:
            saved_to = str(service.save_technique(payload.technique, payload.technique_id))
        except TechniqueNameConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "id": spec.id,
        "filename": f"{spec.id.replace('.', '-')}.yaml",
        "yaml": to_yaml(spec.model_dump(mode="json")),
        "saved_to": saved_to,
        "resolvable": saved_to is not None,
        "next": (
            f"This id now runs: send technique_id {spec.id!r} to /v1/run, or export a client "
            "for it from Prompt text."
            if saved_to
            else "Nothing was saved. Put this file in your registry's techniques/ directory, "
            "or send save=true to keep it on this server."
        ),
    }


@app.delete("/v1/techniques/{technique_id:path}")
def delete_saved_technique(technique_id: str, request: Request) -> dict[str, Any]:
    """Only a saved winner can go. The packaged recipes are not this endpoint's to delete."""
    try:
        removed = _service(request).remove_technique(technique_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"{technique_id} was not saved here, so there is nothing to remove.",
        ) from exc
    return {"removed": technique_id, "file": str(removed) if removed else None}


@app.post("/v1/techniques/import")
def import_technique(payload: TechniqueImportRequest, request: Request) -> dict[str, Any]:
    """Take a technique file written by another server, so an export can travel.

    A saved winner used to live on one machine: the exported client names a
    technique by id, and no other server resolved it. This is the other end of
    that journey.
    """
    try:
        spec = yaml.safe_load(payload.yaml)
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=422, detail=f"This is not readable YAML: {exc}") from exc
    try:
        saved = _service(request).save_technique(spec, payload.technique_id)
    except TechniqueNameConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"id": payload.technique_id or spec.get("id"), "saved_to": str(saved)}


@app.post("/v1/export/runtime", response_model=DeploymentBundle)
def export_deployment(payload: DeploymentExportRequest, request: Request) -> DeploymentBundle:
    service = _service(request)
    try:
        service.resolve_technique(payload.task, payload.technique_id)
        # A packaged recipe is on every server; one saved here is on this one.
        # The export has to carry it, or it only runs where it was made.
        saved = service.user_techniques.get(payload.technique_id)
        return export_runtime(
            task=payload.task,
            technique_id=payload.technique_id,
            language=payload.language,  # type: ignore[arg-type]
            response_schema=payload.response_schema,
            variables=payload.variables,
            exemplars=payload.exemplars,
            technique_yaml=to_yaml(saved.model_dump(mode="json")) if saved else None,
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
