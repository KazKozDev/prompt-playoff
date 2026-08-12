"""Committed benchmark expectations and the CI gate that enforces them."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from pathlib import Path
from typing import Literal

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
from prompt_playoff.measurements import MeasurementStore
from prompt_playoff.providers import ModelProvider, ProviderError, provider_for
from prompt_playoff.registry import Registry

ProviderFactory = Callable[[ModelProfile], ModelProvider]

_NUMERIC_SCORECARD_FIELDS = {
    name for name, field in Scorecard.model_fields.items() if field.annotation in {float, int}
}
VALID_REQUIRE_KEYS = tuple(
    sorted(f"{field}_{bound}" for field in _NUMERIC_SCORECARD_FIELDS for bound in ("min", "max"))
)


class CheckModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model_id: str
    model_class: ModelClass = ModelClass.medium
    capabilities: list[Capability] = Field(default_factory=lambda: [Capability.system_messages])
    base_url: str | None = None
    api_key_env: str | None = None

    def profile(self) -> ModelProfile:
        return ModelProfile(
            provider=self.provider,
            model_id=self.model_id,
            model_class=self.model_class,
            capabilities=set(self.capabilities),
            local=self.provider == "ollama",
            base_url=self.base_url,
            api_key_env=self.api_key_env,
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
        unknown = sorted(set(self.require) - set(VALID_REQUIRE_KEYS))
        if unknown:
            raise ValueError(
                f"unknown require key {unknown[0]!r}; valid keys: {', '.join(VALID_REQUIRE_KEYS)}"
            )
        return self


class CheckFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1]
    model: CheckModelConfig
    checks: list[CheckSpec] = Field(min_length=1)


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
            values = {
                name: float(getattr(report.scorecard, name)) for name in _NUMERIC_SCORECARD_FIELDS
            }
            measured_by_check.append(values)
            thresholds = [_compare(key, required, values) for key, required in spec.require.items()]
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
        return CheckRun(
            status="passed", exit_code=0, config=str(path), checks=results, updated=True
        )
    if has_errors:
        return CheckRun(status="error", exit_code=2, config=str(path), checks=results)
    if has_failures:
        return CheckRun(status="failed", exit_code=1, config=str(path), checks=results)
    return CheckRun(status="passed", exit_code=0, config=str(path), checks=results)


def _compare(key: str, required: float, values: dict[str, float]) -> ThresholdResult:
    field, bound = key.rsplit("_", 1)
    measured = values[field]
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


def _setup_error(exc: Exception, spec: CheckSpec, path: Path) -> str:
    if isinstance(exc, ProviderError):
        return f"Provider setup failed for {spec.name!r}: {exc}; check model credentials/base_url"
    if isinstance(exc, FileNotFoundError):
        return f"Dataset file for {spec.name!r} was not found relative to {path.parent}: {exc}"
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
            match = re.match(r"^(\s+)([a-z0-9_]+)(\s*:\s*)([^#\r\n]*)(.*)$", lines[index])
            if not match or match.group(2) not in spec.require:
                continue
            field, _ = match.group(2).rsplit("_", 1)
            newline = "\n" if lines[index].endswith("\n") else ""
            suffix = match.group(5).rstrip("\r\n")
            if suffix.startswith("#"):
                suffix = f"  {suffix}"
            lines[index] = (
                f"{match.group(1)}{match.group(2)}{match.group(3)}"
                f"{_format_number(values[field])}{suffix}{newline}"
            )
    path.write_text("".join(lines), encoding="utf-8")


def _format_number(value: float) -> str:
    return f"{value:.6g}"
