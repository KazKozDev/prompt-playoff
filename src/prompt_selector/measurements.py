"""Persistence for measured benchmark evidence.

Once a technique has been benchmarked for real, the selector should stop leaning
on the YAML prior for that combination. This store is that feedback loop.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from prompt_selector.domain import MeasuredEvidence, TaskType

DEFAULT_PATH = Path("benchmark-results/measurements.json")


class MeasurementStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _default_path()
        self._records: list[MeasuredEvidence] = []
        self.reload()

    def reload(self) -> None:
        if not self.path.exists():
            self._records = []
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
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
        key = _key(evidence)
        self._records = [item for item in self._records if _key(item) != key]
        self._records.append(evidence)
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"records": [item.model_dump(mode="json") for item in self._records]}
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

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
    custom = os.getenv("PROMPT_SELECTOR_MEASUREMENTS")
    if custom:
        return Path(custom).expanduser()
    return DEFAULT_PATH
