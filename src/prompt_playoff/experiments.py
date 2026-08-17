"""Append-only, privacy-preserving experiment history and version comparisons."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from prompt_playoff.domain import TaskProfile
from prompt_playoff.evals import BenchmarkReport, ComparisonReport, Scorecard
from prompt_playoff.optimizer import OptimizationResult
from prompt_playoff.persistence import advisory_lock, atomic_write_json, quarantine_corrupt_file

DEFAULT_EXPERIMENTS_PATH = Path("benchmark-results/experiments.json")


class MetricSnapshot(BaseModel):
    quality: float
    reliability: float
    mean_latency_seconds: float
    p95_latency_seconds: float
    mean_total_tokens: float
    mean_cost_usd: float | None = None
    total_cost_usd: float | None = None
    failures: int = 0
    runs: int = 0

    @classmethod
    def from_scorecard(cls, scorecard: Scorecard) -> MetricSnapshot:
        return cls(**scorecard.model_dump(include=set(cls.model_fields)))


class ExperimentRecord(BaseModel):
    id: str
    version: int = Field(ge=1)
    kind: Literal["benchmark", "comparison", "optimization"]
    created_at: str
    provider: str
    model_id: str
    dataset: str
    technique_ids: list[str]
    winner: str | None = None
    metrics: dict[str, MetricSnapshot]
    config_hash: str
    prompt_hash: str | None = None
    label: str | None = None
    task: dict[str, Any] | None = None
    dataset_revision: str | None = None
    grader_version: str | None = None
    seed_policy: str | None = None
    environment: dict[str, str] = Field(default_factory=dict)


class MetricDelta(BaseModel):
    metric: str
    before: float | None
    after: float | None
    delta: float | None
    degraded: bool | None


class ExperimentComparison(BaseModel):
    before: ExperimentRecord
    after: ExperimentRecord
    technique_id: str
    deltas: list[MetricDelta]


# One row per measured variant rather than per experiment: a comparison holds
# several and an optimization holds a baseline next to its winner, so a row each
# is what lets a pivot table group by variant, by model or by dataset. "variant"
# is the technique id for a benchmark or a comparison, and "baseline" or the
# winning candidate's id for an optimization.
CSV_COLUMNS = (
    "version",
    "recorded_at",
    "kind",
    "provider",
    "model_id",
    "dataset",
    "variant",
    "is_winner",
    "quality",
    "reliability",
    "mean_latency_seconds",
    "p95_latency_seconds",
    "mean_total_tokens",
    "mean_cost_usd",
    "total_cost_usd",
    "failures",
    "runs",
    "label",
    "technique_ids",
    "experiment_id",
    "config_hash",
    "prompt_hash",
)

# A cell a spreadsheet would run instead of show. Model ids, dataset names and
# labels are all typed by someone or fetched from the Hub, so every text cell is
# checked; numbers are written from floats and never pass through here.
_FORMULA_LEAD = ("=", "+", "-", "@", "\t", "\r")


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    return f"'{text}" if text.startswith(_FORMULA_LEAD) else text


def experiments_csv(records: Iterable[ExperimentRecord]) -> str:
    """Render the history as CSV for Excel, Numbers or Google Sheets.

    Numbers are written unformatted so the spreadsheet reads them as numbers:
    the cost column is dollars, not "$0.000772", and quality is 0.867, not a
    rounded three-decimal string.
    """
    buffer = io.StringIO()
    # Excel wants CRLF, and without a BOM it reads the file in the legacy code
    # page and mangles anything a Hub dataset name might carry.
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(CSV_COLUMNS)
    for record in records:
        winner = record.winner
        order = sorted(record.metrics, key=lambda name: (name != winner, name))
        for variant in order:
            snapshot = record.metrics[variant]
            writer.writerow(
                [
                    _cell(value)
                    for value in (
                        record.version,
                        record.created_at,
                        record.kind,
                        record.provider,
                        record.model_id,
                        record.dataset,
                        variant,
                        variant == winner,
                        snapshot.quality,
                        snapshot.reliability,
                        snapshot.mean_latency_seconds,
                        snapshot.p95_latency_seconds,
                        snapshot.mean_total_tokens,
                        snapshot.mean_cost_usd,
                        snapshot.total_cost_usd,
                        snapshot.failures,
                        snapshot.runs,
                        record.label,
                        " ".join(record.technique_ids),
                        record.id,
                        record.config_hash,
                        record.prompt_hash,
                    )
                ]
            )
    return "\ufeff" + buffer.getvalue()


class ExperimentStore:
    def __init__(self, path: Path | None = None, max_records: int = 500) -> None:
        self.path = path or _default_path()
        self.lock_path = self.path.with_name(f"{self.path.name}.lock")
        self.max_records = max_records
        self.corrupt_path: Path | None = None

    def list(self) -> list[ExperimentRecord]:
        with advisory_lock(self.lock_path):
            return sorted(self._load_unlocked(), key=lambda item: item.created_at, reverse=True)

    def get(self, record_id: str) -> ExperimentRecord | None:
        return next((item for item in self.list() if item.id == record_id), None)

    def add_benchmark(self, report: BenchmarkReport, task: TaskProfile) -> ExperimentRecord:
        return self._add(
            kind="benchmark",
            task=task,
            dataset=report.dataset,
            technique_ids=[report.technique_id],
            winner=report.technique_id,
            metrics={report.technique_id: MetricSnapshot.from_scorecard(report.scorecard)},
            prompt=report.prompt_preview,
            reproducibility={
                "dataset_revision": report.dataset_revision,
                "grader_version": report.grader_version,
                "seed_policy": report.seed_policy,
            },
        )

    def add_comparison(
        self, comparison: ComparisonReport, reports: list[BenchmarkReport], task: TaskProfile
    ) -> ExperimentRecord:
        return self._add(
            kind="comparison",
            task=task,
            dataset=comparison.dataset,
            technique_ids=[item.technique_id for item in comparison.entries],
            winner=comparison.winner,
            metrics={
                item.technique_id: MetricSnapshot.from_scorecard(item.scorecard)
                for item in comparison.entries
            },
            prompt=[report.prompt_preview for report in reports],
            reproducibility={
                "dataset_revision": reports[0].dataset_revision if reports else None,
                "grader_version": reports[0].grader_version if reports else None,
                "seed_policy": reports[0].seed_policy if reports else None,
            },
        )

    def add_optimization(self, result: OptimizationResult, task: TaskProfile) -> ExperimentRecord:
        return self._add(
            kind="optimization",
            task=task,
            dataset=result.dataset,
            technique_ids=[result.winner.technique_id],
            winner=result.winner.id,
            metrics={
                "baseline": MetricSnapshot.from_scorecard(result.baseline_validation),
                result.winner.id: MetricSnapshot.from_scorecard(result.winner_validation),
            },
            prompt=result.compiled_prompt,
            reproducibility={},
        )

    def compare(
        self, before_id: str, after_id: str, technique_id: str | None = None
    ) -> ExperimentComparison:
        before, after = self.get(before_id), self.get(after_id)
        if before is None or after is None:
            raise ValueError("Both experiment ids must exist")
        common = sorted(set(before.metrics) & set(after.metrics))
        selected = technique_id or (common[0] if len(common) == 1 else None)
        if selected is None or selected not in common:
            raise ValueError("Choose a technique present in both experiments")
        left, right = before.metrics[selected], after.metrics[selected]
        directions = {
            "quality": "higher",
            "reliability": "higher",
            "mean_latency_seconds": "lower",
            "p95_latency_seconds": "lower",
            "mean_total_tokens": "lower",
            "mean_cost_usd": "lower",
            "total_cost_usd": "lower",
            "failures": "lower",
        }
        deltas = []
        for metric, direction in directions.items():
            old, new = getattr(left, metric), getattr(right, metric)
            delta = None if old is None or new is None else round(float(new) - float(old), 8)
            degraded = (
                None if delta is None else (delta < 0 if direction == "higher" else delta > 0)
            )
            deltas.append(
                MetricDelta(metric=metric, before=old, after=new, delta=delta, degraded=degraded)
            )
        return ExperimentComparison(
            before=before, after=after, technique_id=selected, deltas=deltas
        )

    def _add(
        self,
        *,
        kind: Literal["benchmark", "comparison", "optimization"],
        task: TaskProfile,
        dataset: str,
        technique_ids: list[str],
        winner: str | None,
        metrics: dict[str, MetricSnapshot],
        prompt: Any,
        reproducibility: dict[str, str | None],
    ) -> ExperimentRecord:
        clean_task = task.model_dump(mode="json", exclude={"model": {"api_key"}})
        signature = {
            "kind": kind,
            "provider": task.model.provider,
            "model_id": task.model.model_id,
            "dataset": dataset,
            "techniques": sorted(technique_ids),
        }
        with advisory_lock(self.lock_path):
            records = self._load_unlocked()
            matching = [item.version for item in records if _signature(item) == signature]
            record = ExperimentRecord(
                id=uuid.uuid4().hex[:12],
                version=max(matching, default=0) + 1,
                kind=kind,
                created_at=_now(),
                provider=task.model.provider,
                model_id=task.model.model_id,
                dataset=dataset,
                technique_ids=technique_ids,
                winner=winner,
                metrics=metrics,
                config_hash=_hash(clean_task),
                prompt_hash=_hash(prompt) if prompt else None,
                task=clean_task,
                dataset_revision=reproducibility.get("dataset_revision"),
                grader_version=reproducibility.get("grader_version"),
                seed_policy=reproducibility.get("seed_policy"),
                environment={"prompt_playoff": "local", "python": os.sys.version.split()[0]},
            )
            records.append(record)
            self._write_unlocked(records[-self.max_records :])
            return record

    def _load_unlocked(self) -> list[ExperimentRecord]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return [
                ExperimentRecord.model_validate(item) for item in payload.get("experiments", [])
            ]
        except (OSError, ValueError, TypeError):
            try:
                self.corrupt_path = quarantine_corrupt_file(self.path)
            except OSError:
                self.corrupt_path = self.path
            return []

    def _write_unlocked(self, records: list[ExperimentRecord]) -> None:
        atomic_write_json(
            self.path,
            {"version": 1, "experiments": [item.model_dump(mode="json") for item in records]},
        )


def _signature(item: ExperimentRecord) -> dict[str, Any]:
    return {
        "kind": item.kind,
        "provider": item.provider,
        "model_id": item.model_id,
        "dataset": item.dataset,
        "techniques": sorted(item.technique_ids),
    }


def _hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()[:16]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _default_path() -> Path:
    return Path(os.getenv("PROMPT_PLAYOFF_EXPERIMENTS_PATH", DEFAULT_EXPERIMENTS_PATH)).expanduser()
