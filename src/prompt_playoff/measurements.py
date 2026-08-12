"""Persistence for measured benchmark evidence.

Once a technique has been benchmarked for real, the selector should stop leaning
on the YAML prior for that combination. This store is that feedback loop.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from prompt_playoff.domain import MeasuredEvidence, TaskType
from prompt_playoff.persistence import advisory_lock, atomic_write_json, quarantine_corrupt_file

DEFAULT_PATH = Path("benchmark-results/measurements.json")


class MeasurementStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _default_path()
        self.lock_path = self.path.with_name(f"{self.path.name}.lock")
        self.corrupt_path: Path | None = None
        self._records: list[MeasuredEvidence] = []
        self.reload()

    def reload(self) -> None:
        with advisory_lock(self.lock_path):
            self._reload_unlocked()

    def _reload_unlocked(self) -> None:
        if not self.path.exists():
            self._records = []
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            try:
                self.corrupt_path = quarantine_corrupt_file(self.path)
            except OSError:
                self.corrupt_path = self.path
            self._records = []
            return
        records: list[MeasuredEvidence] = []
        for item in payload.get("records", []):
            try:
                records.append(MeasuredEvidence.model_validate(item))
            except Exception:
                continue
        self._records = records

    @property
    def records(self) -> list[MeasuredEvidence]:
        return list(self._records)

    def record(self, evidence: MeasuredEvidence) -> None:
        """Newest measurement for a key wins; history is not needed for ranking."""
        with advisory_lock(self.lock_path):
            self._reload_unlocked()
            key = _key(evidence)
            self._records = [item for item in self._records if _key(item) != key]
            self._records.append(evidence)
            self._save_unlocked()

    def save(self) -> None:
        with advisory_lock(self.lock_path):
            local_records = list(self._records)
            self._reload_unlocked()
            merged = {_key(item): item for item in self._records}
            merged.update({_key(item): item for item in local_records})
            self._records = list(merged.values())
            self._save_unlocked()

    def _save_unlocked(self) -> None:
        payload = {"records": [item.model_dump(mode="json") for item in self._records]}
        atomic_write_json(self.path, payload)

    @property
    def recovery_warning(self) -> str | None:
        if self.corrupt_path is None:
            return None
        return f"Unreadable measurement data was moved to {self.corrupt_path}"

    def lookup(
        self,
        technique_id: str,
        task_type: TaskType,
        provider: str,
        model_id: str,
    ) -> MeasuredEvidence | None:
        """Exact (technique, task, provider, model) only.

        Falling back to "some other model measured this technique" was wrong: a
        3B and a 7B model disagree about which technique wins, which is the whole
        reason this project measures instead of assuming. A near miss is not
        evidence, so it stays a prior and is labelled as one.
        """
        matched = [
            item
            for item in self._records
            if item.technique_id == technique_id
            and item.task_type == task_type
            and item.provider == provider
            and item.model_id == model_id
        ]
        if not matched:
            return None
        return max(matched, key=lambda item: (item.recorded_at, item.examples * item.repeats))

    def coverage(self) -> dict[str, int]:
        return {
            "records": len(self._records),
            "techniques": len({item.technique_id for item in self._records}),
            "models": len({(item.provider, item.model_id) for item in self._records}),
        }


def _key(evidence: MeasuredEvidence) -> tuple[str, str, str, str, str]:
    return (
        evidence.technique_id,
        evidence.task_type.value,
        evidence.provider,
        evidence.model_id,
        evidence.dataset,
    )


def _default_path() -> Path:
    custom = os.getenv("PROMPT_PLAYOFF_MEASUREMENTS")
    if custom:
        return Path(custom).expanduser()
    return DEFAULT_PATH
