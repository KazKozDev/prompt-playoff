"""Committed benchmark expectations and the CI gate that enforces them."""

from __future__ import annotations

import asyncio
import os
import re
import types
from collections.abc import Callable
from pathlib import Path
from typing import Literal, get_args

import httpx
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from prompt_playoff.domain import (
    Capability,
    Constraints,
    ModelClass,
    ModelProfile,
    TaskProfile,
    TaskType,
)
from prompt_playoff.evals import BenchmarkRunner, Scorecard, load_jsonl
from prompt_playoff.graders import REFERENCE_OVERLAP_GRADERS, describe, grader_names
from prompt_playoff.measurements import MeasurementStore
from prompt_playoff.providers import ModelProvider, ProviderError, provider_for
from prompt_playoff.registry import Registry

ProviderFactory = Callable[[ModelProfile], ModelProvider]

#: Scorecard numbers that describe the metric rather than the prompt, so a bar
#: on one would move when the examples change and never when the prompt does.
_NOT_THRESHOLDS = {"quality_chance_level"}
_NUMERIC_SCORECARD_FIELDS = {
    name
    for name, field in Scorecard.model_fields.items()
    if name not in _NOT_THRESHOLDS
    and (
        field.annotation in {float, int}
        or (
            isinstance(field.annotation, types.UnionType)
            and any(item in {float, int} for item in get_args(field.annotation))
        )
    )
}
VALID_REQUIRE_KEYS = tuple(
    sorted(f"{field}_{bound}" for field in _NUMERIC_SCORECARD_FIELDS for bound in ("min", "max"))
)
#: The prefix that gates one named grader instead of a headline number.
#:
#: `quality` is whichever grader won the preference order, which is the right
#: bar for a task with one right answer and no bar at all for open-ended work:
#: there the graders that can decide anything — every required fact present, no
#: forbidden wording, inside the length the channel allows — are not the
#: headline and never were. Without a way to name one, half the catalogue could
#: only be gated on a number that does not describe it, which is the same as
#: not being gated. With it, `grade.contains_all_min: 0.95` is a CI failure
#: when a rewritten prompt starts dropping order numbers from replies.
GRADE_PREFIX = "grade."


def parse_require_key(key: str) -> tuple[str, str]:
    """Split a require key into what it measures and which side of it is bounded.

    Returns the measurement (`quality`, or `grade.contains_all`) and the bound
    (`min` or `max`). Raises ValueError with wording a person can act on, since
    this is the one place a typo in a committed file gets caught.
    """
    measure, _, bound = key.rpartition("_")
    if bound not in {"min", "max"} or not measure:
        raise ValueError(
            f"require key {key!r} must end in '_min' or '_max'; "
            f"valid keys: {', '.join(VALID_REQUIRE_KEYS)}, "
            f"or {GRADE_PREFIX}<grader>_min / _max for one named grader"
        )
    if measure.startswith(GRADE_PREFIX):
        name = measure[len(GRADE_PREFIX) :]
        if name not in grader_names():
            raise ValueError(
                f"require key {key!r} names no grader; known graders: {', '.join(grader_names())}"
            )
    elif measure not in _NUMERIC_SCORECARD_FIELDS:
        raise ValueError(
            f"unknown require key {key!r}; valid keys: {', '.join(VALID_REQUIRE_KEYS)}, "
            f"or {GRADE_PREFIX}<grader>_min / _max for one named grader"
        )
    return measure, bound


class CheckModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model_id: str
    model_class: ModelClass = ModelClass.medium
    capabilities: list[Capability] = Field(default_factory=lambda: [Capability.system_messages])
    base_url: str | None = None
    api_key_env: str | None = None
    input_cost_per_million_usd: float | None = Field(default=None, ge=0)
    output_cost_per_million_usd: float | None = Field(default=None, ge=0)

    def profile(self) -> ModelProfile:
        return ModelProfile(
            provider=self.provider,
            model_id=self.model_id,
            model_class=self.model_class,
            capabilities=set(self.capabilities),
            local=self.provider == "ollama",
            base_url=self.base_url,
            api_key_env=self.api_key_env,
            input_cost_per_million_usd=self.input_cost_per_million_usd,
            output_cost_per_million_usd=self.output_cost_per_million_usd,
        )


class CheckSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    technique: str
    task: TaskType
    dataset: str | None = None
    dataset_file: str | None = None
    repeats: int = Field(default=1, ge=1, le=10)
    strict_json: bool = False
    timeout_seconds: float = Field(default=120, gt=0)
    require: dict[str, float]

    @model_validator(mode="after")
    def validate_sources_and_requirements(self) -> CheckSpec:
        if bool(self.dataset) == bool(self.dataset_file):
            raise ValueError("set exactly one config key: dataset or dataset_file")
        if not self.require:
            raise ValueError("require must contain at least one <Scorecard field>_min or _max key")
        for key in sorted(self.require):
            parse_require_key(key)
        return self


class CheckFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1]
    model: CheckModelConfig
    checks: list[CheckSpec] = Field(min_length=1)
    notifications: NotificationConfig = Field(default_factory=lambda: NotificationConfig())


class NotificationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    webhook_urls: list[str] = Field(default_factory=list, max_length=5)


class ThresholdResult(BaseModel):
    field: str
    bound: Literal["min", "max"]
    measured: float
    required: float
    passed: bool
    difference: float
    breach: float


class CheckResult(BaseModel):
    name: str
    technique: str
    status: Literal["passed", "failed", "error"]
    thresholds: list[ThresholdResult] = Field(default_factory=list)
    error: str | None = None


class CheckRun(BaseModel):
    status: Literal["passed", "failed", "error"]
    exit_code: Literal[0, 1, 2]
    config: str
    checks: list[CheckResult]
    updated: bool = False
    notifications: list[NotificationDelivery] = Field(default_factory=list)


class NotificationDelivery(BaseModel):
    channel: Literal["webhook"] = "webhook"
    status: Literal["sent", "failed"]
    destination: str
    error: str | None = None


class CheckConfigError(ValueError):
    pass


def load_check_file(path: Path) -> CheckFile:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        message = f"Config file not found: {path}; pass --config with a valid path"
        raise CheckConfigError(message) from exc
    except (OSError, yaml.YAMLError) as exc:
        raise CheckConfigError(f"Cannot read YAML config {path}: {exc}") from exc
    try:
        return CheckFile.model_validate(raw)
    except ValidationError as exc:
        raise CheckConfigError(f"Invalid config {path}: {exc}") from exc


async def run_checks(
    path: Path,
    *,
    record: bool = True,
    update: bool = False,
    provider_factory: ProviderFactory = provider_for,
    measurements: MeasurementStore | None = None,
    notification_transport: httpx.AsyncBaseTransport | None = None,
) -> CheckRun:
    config = load_check_file(path)
    try:
        registry = Registry.load()
        profile = config.model.profile()
        store = (
            measurements if measurements is not None else (MeasurementStore() if record else None)
        )
    except Exception as exc:
        raise CheckConfigError(f"Cannot set up checks from {path}: {exc}") from exc
    results: list[CheckResult] = []
    measured_by_check: list[dict[str, float] | None] = []

    for spec in config.checks:
        try:
            technique = registry.technique(spec.technique)
            if spec.dataset_file:
                dataset_path = (path.parent / spec.dataset_file).resolve()
                examples = load_jsonl(dataset_path)
                dataset_name = dataset_path.stem
            else:
                dataset_name = spec.dataset or ""
                examples = load_jsonl(registry.dataset_path(dataset_name))
            task = TaskProfile(
                task_type=spec.task,
                output_contract="json_schema" if spec.strict_json else "free_text",
                constraints=Constraints(
                    strict_json=spec.strict_json,
                    requires_validation=True,
                    max_calls=20,
                ),
                model=profile,
            )
            provider = provider_factory(profile)
            report = await BenchmarkRunner(provider).run(
                dataset=examples,
                task=task,
                technique=technique,
                repeats=spec.repeats,
                timeout_seconds=spec.timeout_seconds,
                dataset_name=dataset_name,
            )
            if report.runs and all(item.error for item in report.runs):
                errors = sorted({item.error or "provider failed" for item in report.runs})
                raise ProviderError("; ".join(errors))
            if record:
                assert store is not None
                store.record(report.to_evidence())
            measured = measured_values(spec.require, report.scorecard)
            measured_by_check.append(measured)
            thresholds = [
                _compare(key, required, measured[key]) for key, required in spec.require.items()
            ]
            status = "passed" if all(item.passed for item in thresholds) else "failed"
            results.append(
                CheckResult(
                    name=spec.name,
                    technique=spec.technique,
                    status=status,
                    thresholds=thresholds,
                )
            )
        except Exception as exc:
            measured_by_check.append(None)
            results.append(
                CheckResult(
                    name=spec.name,
                    technique=spec.technique,
                    status="error",
                    error=_setup_error(exc, spec, path),
                )
            )
        await asyncio.sleep(0)

    has_errors = any(item.status == "error" for item in results)
    has_failures = any(item.status == "failed" for item in results)
    if update and not has_errors:
        _update_require_values(path, config, measured_by_check)
        for item in results:
            item.status = "passed"
            for threshold in item.thresholds:
                threshold.required = threshold.measured
                threshold.difference = 0.0
                threshold.breach = 0.0
                threshold.passed = True
        result = CheckRun(
            status="passed", exit_code=0, config=str(path), checks=results, updated=True
        )
    elif has_errors:
        result = CheckRun(status="error", exit_code=2, config=str(path), checks=results)
    elif has_failures:
        result = CheckRun(status="failed", exit_code=1, config=str(path), checks=results)
    else:
        result = CheckRun(status="passed", exit_code=0, config=str(path), checks=results)
    if result.exit_code and not update:
        urls = list(config.notifications.webhook_urls)
        if environment_url := os.getenv("PROMPT_PLAYOFF_WEBHOOK_URL"):
            urls.append(environment_url)
        result.notifications = await _send_webhooks(
            result, list(dict.fromkeys(urls)), notification_transport
        )
    return result


async def _send_webhooks(
    result: CheckRun,
    urls: list[str],
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[NotificationDelivery]:
    deliveries: list[NotificationDelivery] = []
    payload = {
        "event": "prompt_playoff.regression",
        "status": result.status,
        "exit_code": result.exit_code,
        "config": result.config,
        "checks": [item.model_dump(mode="json") for item in result.checks],
    }
    async with httpx.AsyncClient(timeout=10, transport=transport) as client:
        for url in urls:
            destination = _redact_destination(url)
            try:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                deliveries.append(NotificationDelivery(status="sent", destination=destination))
            except (httpx.HTTPError, ValueError) as exc:
                deliveries.append(
                    NotificationDelivery(
                        status="failed",
                        destination=destination,
                        error=str(exc) or type(exc).__name__,
                    )
                )
    return deliveries


def _redact_destination(url: str) -> str:
    try:
        parsed = httpx.URL(url)
        return str(parsed.copy_with(path="/…", query=None, fragment=None))
    except Exception:
        return "invalid webhook URL"


def overlap_refusal(measure: str, quality_grader: str | None) -> str | None:
    """Why a bar on `quality` is not a bar at all when the headline is word overlap.

    This is the gate refusing to be decorative. A committed `quality_min` reads
    as "answers must be this good"; when quality came from comparing an answer
    with one reference answer, what it actually pins is how closely the model
    reproduces one person's wording — which a rewritten prompt can lose while
    getting better, and a copy-paste prompt can hold while getting worse. Rather
    than enforce that under a name it does not deserve, the check stops and says
    what to write instead.
    """
    if measure != "quality" or quality_grader not in REFERENCE_OVERLAP_GRADERS:
        return None
    return (
        f"quality on this run is {quality_grader} — {describe(quality_grader)} — so a "
        "quality bar here would commit CI to how closely answers echo one reference, "
        "not to whether they are any good. Give the rows requirements a rule can "
        "check (contains_all, forbidden_content, length_limit, regex_match, "
        "grounding_overlap) and gate those with grade.<grader>_min; or write "
        f"{GRADE_PREFIX}{quality_grader}_min to say you are watching this metric drift "
        "rather than claiming a bar on quality."
    )


def measured_values(require: dict[str, float], scorecard: Scorecard) -> dict[str, float]:
    """The number each require key is about, or an error naming what is missing.

    A threshold with nothing behind it is the one outcome a gate must never
    report as passed, so every way a key can fail to resolve ends here as a
    refusal rather than a default.
    """
    resolved: dict[str, float] = {}
    for key in require:
        measure, _ = parse_require_key(key)
        if refusal := overlap_refusal(measure, scorecard.quality_grader):
            raise CheckConfigError(f"Cannot enforce {key}: {refusal}")
        if measure.startswith(GRADE_PREFIX):
            name = measure[len(GRADE_PREFIX) :]
            if name not in scorecard.grades:
                raise CheckConfigError(
                    f"Cannot enforce {key} because this run produced no {name} score. "
                    "A grader only runs when the dataset names it or the data implies it — "
                    f'add {name!r} to the rows\' "graders" and give it what it needs.'
                )
            resolved[key] = float(scorecard.grades[name])
            continue
        value = getattr(scorecard, measure, None)
        if value is None:
            raise CheckConfigError(
                f"Cannot enforce {measure} because model pricing is not configured"
            )
        resolved[key] = float(value)
    return resolved


def _compare(key: str, required: float, measured: float) -> ThresholdResult:
    field, bound = parse_require_key(key)
    passed = measured >= required if bound == "min" else measured <= required
    difference = measured - required
    breach = 0.0 if passed else abs(difference)
    return ThresholdResult(
        field=field,
        bound=bound,  # type: ignore[arg-type]
        measured=measured,
        required=required,
        passed=passed,
        difference=difference,
        breach=breach,
    )


# --------------------------------------------------------------------------- #
# the same thresholds, applied to a release instead of to a CI run
# --------------------------------------------------------------------------- #


class ReleaseGate(BaseModel):
    """Whether a recorded run clears the bar this project committed to.

    The bar is the one already in `prompt-playoff.yaml` — the same numbers CI
    enforces. Approving a release used to need only a human to click yes, which
    meant the committed thresholds guarded the repository and not the thing
    actually being shipped.
    """

    status: Literal[
        "passed", "failed", "stale", "unverified", "unmeasured", "unenforceable", "not_configured"
    ]
    config: str | None = None
    checks: list[str] = Field(default_factory=list)
    thresholds: list[ThresholdResult] = Field(default_factory=list)
    reason: str | None = None

    @property
    def blocks_approval(self) -> bool:
        """A gate that could not be evaluated is not a gate that passed."""
        return self.status in {"failed", "stale", "unverified", "unmeasured", "unenforceable"}


def default_check_path() -> Path:
    return Path(os.getenv("PROMPT_PLAYOFF_CHECKS", "prompt-playoff.yaml")).expanduser()


def release_gate(
    technique_id: str,
    metrics: dict[str, float] | None,
    path: Path | None = None,
    evidence: str = "measured",
    dataset_changed: bool = False,
    grades: dict[str, float] | None = None,
    quality_grader: str | None = None,
) -> ReleaseGate:
    """Read the committed thresholds for this technique and apply them to a run.

    Nothing here calls a model: the release cites a recorded run, and that run's
    numbers are what the bar is applied to. Re-measuring inside an approval would
    turn one click into a job, and would score a different sample than the one
    the release says it was approved on.
    """
    path = path or default_check_path()
    if not path.is_file():
        return ReleaseGate(
            status="not_configured",
            reason=f"No committed thresholds: {path} does not exist.",
        )
    try:
        config = load_check_file(path)
    except CheckConfigError as exc:
        return ReleaseGate(status="unenforceable", config=str(path), reason=str(exc))

    specs = [item for item in config.checks if item.technique == technique_id]
    if not specs:
        return ReleaseGate(
            status="not_configured",
            config=str(path),
            reason=(
                f"{path} commits no thresholds for {technique_id}, so there is no bar to "
                "clear. Add a check for it to gate releases on numbers."
            ),
        )
    names = [item.name for item in specs]
    # A run that measured different text is not this prompt's number, however
    # good it is. Registering such a release is allowed and recorded; shipping
    # it on numbers that describe something else is not.
    if evidence == "indirect":
        return ReleaseGate(
            status="unverified",
            config=str(path),
            checks=names,
            reason=(
                "The run this release cites measured a different prompt, so its numbers are "
                "not about the text being shipped. Measure this prompt, then register it."
            ),
        )
    if dataset_changed:
        return ReleaseGate(
            status="stale",
            config=str(path),
            checks=names,
            reason=(
                "The examples have changed since this run. Its numbers describe rows that no "
                "longer exist, so clearing the bar on them proves nothing about today's data. "
                "Measure again on the current set."
            ),
        )
    if not metrics or evidence == "unverified":
        return ReleaseGate(
            status="unmeasured",
            config=str(path),
            checks=names,
            reason=(
                f"{path} sets a bar for {technique_id}, but this release cites no recorded "
                "run to apply it to. Measure the prompt, then register it."
            ),
        )
    required: dict[str, float] = {}
    for spec in specs:
        required |= spec.require
    available = dict(metrics)
    for name, value in (grades or {}).items():
        available[f"{GRADE_PREFIX}{name}"] = value
    for key in sorted(required):
        measure, _ = parse_require_key(key)
        if refusal := overlap_refusal(measure, quality_grader):
            return ReleaseGate(
                status="unenforceable", config=str(path), checks=names, reason=refusal
            )
    missing = sorted({parse_require_key(key)[0] for key in required} - set(available))
    if missing:
        return ReleaseGate(
            status="unenforceable",
            config=str(path),
            checks=names,
            reason=(
                f"The recorded run carries no {', '.join(missing)}, so "
                f"{', '.join(sorted(required))} cannot be checked against it."
            ),
        )
    thresholds = [
        _compare(key, value, available[parse_require_key(key)[0]])
        for key, value in sorted(required.items())
    ]
    passed = all(item.passed for item in thresholds)
    breached = [
        f"{item.field} {item.measured:g} vs {item.bound} {item.required:g}"
        for item in thresholds
        if not item.passed
    ]
    return ReleaseGate(
        status="passed" if passed else "failed",
        config=str(path),
        checks=names,
        thresholds=thresholds,
        reason=None if passed else f"Below the committed bar: {'; '.join(breached)}.",
    )


def _setup_error(exc: Exception, spec: CheckSpec, path: Path) -> str:
    if isinstance(exc, ProviderError):
        return f"Provider setup failed for {spec.name!r}: {exc}; check model credentials/base_url"
    if isinstance(exc, FileNotFoundError):
        return f"Dataset file for {spec.name!r} was not found relative to {path.parent}: {exc}"
    if isinstance(exc, CheckConfigError):
        # A refusal to enforce a threshold is not a setup failure, and it
        # already names both the check and what to write instead; prefixing it
        # with "Setup failed" would bury the fix under a wrong diagnosis.
        return f"{spec.name!r}: {exc}"
    return f"Setup failed for {spec.name!r}: {exc}"


def _update_require_values(
    path: Path,
    config: CheckFile,
    measured_by_check: list[dict[str, float] | None],
) -> None:
    """Change only scalar requirement values so comments and ordering survive updates."""
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    check_starts = [
        index for index, line in enumerate(lines) if re.match(r"^\s*-\s+name\s*:", line)
    ]
    if len(check_starts) != len(config.checks):
        raise CheckConfigError("Cannot update config safely: checks must use '- name:' entries")
    check_starts.append(len(lines))
    for position, (spec, values) in reversed(
        list(enumerate(zip(config.checks, measured_by_check, strict=True)))
    ):
        if values is None:
            continue
        start, end = check_starts[position], check_starts[position + 1]
        require_line = next(
            (
                index
                for index in range(start, end)
                if re.match(r"^\s+require\s*:\s*(?:#.*)?$", lines[index])
            ),
            None,
        )
        if require_line is None:
            raise CheckConfigError(f"Cannot update {spec.name!r}: require must be a YAML block")
        for index in range(require_line + 1, end):
            match = re.match(r"^(\s+)([a-z0-9_.]+)(\s*:\s*)([^#\r\n]*)(.*)$", lines[index])
            if not match or match.group(2) not in spec.require:
                continue
            newline = "\n" if lines[index].endswith("\n") else ""
            suffix = match.group(5).rstrip("\r\n")
            if suffix.startswith("#"):
                suffix = f"  {suffix}"
            lines[index] = (
                f"{match.group(1)}{match.group(2)}{match.group(3)}"
                f"{_format_number(values[match.group(2)])}{suffix}{newline}"
            )
    path.write_text("".join(lines), encoding="utf-8")


def _format_number(value: float) -> str:
    return f"{value:.6g}"
