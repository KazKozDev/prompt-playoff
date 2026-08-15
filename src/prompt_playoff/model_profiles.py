"""Secret-free model profiles persisted for reuse by the local application."""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from prompt_playoff.domain import ModelProfile
from prompt_playoff.persistence import advisory_lock, atomic_write_json, quarantine_corrupt_file

DEFAULT_PROFILES_PATH = Path("benchmark-results/model-profiles.json")


class SavedModelProfile(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    name: str = Field(min_length=1, max_length=100)
    profile: ModelProfile
    created_at: str
    updated_at: str


class ModelProfileStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _default_path()
        self.lock_path = self.path.with_name(f"{self.path.name}.lock")
        self.corrupt_path: Path | None = None

    def list(self) -> list[SavedModelProfile]:
        with advisory_lock(self.lock_path):
            return sorted(self._load_unlocked(), key=lambda item: item.name.lower())

    def save(
        self, name: str, profile: ModelProfile, profile_id: str | None = None
    ) -> SavedModelProfile:
        now = _now()
        clean = profile.model_copy(update={"api_key": None})
        identifier = _slug(profile_id or name)
        with advisory_lock(self.lock_path):
            records = self._load_unlocked()
            previous = next((item for item in records if item.id == identifier), None)
            saved = SavedModelProfile(
                id=identifier,
                name=name.strip(),
                profile=clean,
                created_at=previous.created_at if previous else now,
                updated_at=now,
            )
            records = [item for item in records if item.id != identifier]
            records.append(saved)
            self._write_unlocked(records)
            return saved

    def delete(self, profile_id: str) -> bool:
        with advisory_lock(self.lock_path):
            records = self._load_unlocked()
            kept = [item for item in records if item.id != profile_id]
            if len(kept) == len(records):
                return False
            self._write_unlocked(kept)
            return True

    def _load_unlocked(self) -> list[SavedModelProfile]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return [SavedModelProfile.model_validate(item) for item in payload.get("profiles", [])]
        except (OSError, ValueError, TypeError):
            try:
                self.corrupt_path = quarantine_corrupt_file(self.path)
            except OSError:
                self.corrupt_path = self.path
            return []

    def _write_unlocked(self, records: list[SavedModelProfile]) -> None:
        atomic_write_json(
            self.path,
            {"version": 1, "profiles": [item.model_dump(mode="json") for item in records]},
        )


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9._-]+", "-", value.lower()).strip("-._")
    if not slug:
        raise ValueError("Profile name must contain at least one letter or number")
    return slug[:64]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _default_path() -> Path:
    return Path(os.getenv("PROMPT_PLAYOFF_PROFILES_PATH", DEFAULT_PROFILES_PATH)).expanduser()
