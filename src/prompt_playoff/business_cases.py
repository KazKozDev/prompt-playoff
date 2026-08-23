"""Persistent user-owned business cases for the experiment portfolio."""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from prompt_playoff.persistence import (
    advisory_lock,
    atomic_write_json,
    quarantine_corrupt_file,
)

DEFAULT_BUSINESS_CASES_PATH = Path("benchmark-results/business-cases.json")


class BusinessCaseRecord(BaseModel):
    id: str = Field(min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=4000)
    created_at: str
    updated_at: str
    archived: bool = False


class BusinessCaseStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _default_path()
        self.lock_path = self.path.with_name(f"{self.path.name}.lock")
        self.corrupt_path: Path | None = None

    def list(self, *, include_archived: bool = False) -> list[BusinessCaseRecord]:
        with advisory_lock(self.lock_path):
            records = self._load_unlocked()
        visible = records if include_archived else [item for item in records if not item.archived]
        return sorted(visible, key=lambda item: (item.archived, item.name.casefold(), item.id))

    def get(self, case_id: str) -> BusinessCaseRecord | None:
        with advisory_lock(self.lock_path):
            return next((item for item in self._load_unlocked() if item.id == case_id), None)

    def create(self, name: str, description: str = "") -> BusinessCaseRecord:
        clean_name = _required(name, "Business case name")
        now = _now()
        with advisory_lock(self.lock_path):
            records = self._load_unlocked()
            base = _slug(clean_name)
            used = {item.id for item in records}
            case_id = base
            if case_id in used:
                case_id = f"{base}-{uuid.uuid4().hex[:6]}"
            record = BusinessCaseRecord(
                id=case_id,
                name=clean_name,
                description=description.strip(),
                created_at=now,
                updated_at=now,
            )
            records.append(record)
            self._write_unlocked(records)
        return record

    def update(
        self,
        case_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        archived: bool | None = None,
    ) -> BusinessCaseRecord:
        with advisory_lock(self.lock_path):
            records = self._load_unlocked()
            index = next((i for i, item in enumerate(records) if item.id == case_id), None)
            if index is None:
                raise KeyError(case_id)
            current = records[index]
            record = BusinessCaseRecord.model_validate(
                {
                    **current.model_dump(mode="json"),
                    "name": (
                        _required(name, "Business case name") if name is not None else current.name
                    ),
                    "description": (
                        description.strip() if description is not None else current.description
                    ),
                    "archived": archived if archived is not None else current.archived,
                    "updated_at": _now(),
                }
            )
            records[index] = record
            self._write_unlocked(records)
        return record

    def _load_unlocked(self) -> list[BusinessCaseRecord]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return [
                BusinessCaseRecord.model_validate(item)
                for item in payload.get("business_cases", [])
            ]
        except (OSError, ValueError, TypeError):
            try:
                self.corrupt_path = quarantine_corrupt_file(self.path)
            except OSError:
                self.corrupt_path = self.path
            return []

    def _write_unlocked(self, records: list[BusinessCaseRecord]) -> None:
        atomic_write_json(
            self.path,
            {
                "version": 1,
                "business_cases": [item.model_dump(mode="json") for item in records],
            },
        )


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug[:120] or f"case-{uuid.uuid4().hex[:8]}"


def _required(value: str, label: str) -> str:
    clean = value.strip()
    if not clean:
        raise ValueError(f"{label} cannot be empty")
    return clean


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _default_path() -> Path:
    return Path(
        os.getenv("PROMPT_PLAYOFF_BUSINESS_CASES_PATH", DEFAULT_BUSINESS_CASES_PATH)
    ).expanduser()
