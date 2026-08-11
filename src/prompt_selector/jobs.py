"""Persistent local job queue for work that takes real model calls.

Benchmarks and optimization runs take minutes, so the HTTP layer starts them as
jobs and the client polls. Jobs execute in one process without a broker, while
their status and event history are atomically persisted across app restarts.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from prompt_selector.persistence import atomic_write_json, quarantine_corrupt_file

DEFAULT_JOBS_PATH = Path("benchmark-results/jobs.json")


class Job(BaseModel):
    id: str
    kind: str
    status: str = "pending"  # pending | running | done | error
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    progress: dict[str, Any] = Field(default_factory=dict)
    events: list[dict[str, Any]] = Field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str | None = None


class JobStore:
    def __init__(self, path: Path | None = None, max_events: int | None = None) -> None:
        self.path = path or _default_jobs_path()
        self._jobs: dict[str, Job] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self.max_events = max_events
        self.corrupt_path: Path | None = None
        self._load()

    def create(self, kind: str) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind, created_at=_now())
        self._jobs[job.id] = job
        self._append_event(job, {"event": "queued"})
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        return sorted(self._jobs.values(), key=lambda item: item.created_at, reverse=True)

    def note(self, job_id: str, event: dict[str, Any]) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        job.progress = event
        self._append_event(job, event)

    def _append_event(self, job: Job, event: dict[str, Any]) -> None:
        job.events.append({**event, "at": _now()})
        if self.max_events is not None and len(job.events) > self.max_events:
            del job.events[: len(job.events) - self.max_events]
        self._save()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            jobs = [Job.model_validate(item) for item in payload.get("jobs", [])]
        except (OSError, json.JSONDecodeError, TypeError, ValidationError):
            try:
                self.corrupt_path = quarantine_corrupt_file(self.path)
            except OSError:
                self.corrupt_path = self.path
            return

        interrupted = False
        for job in jobs:
            if job.status in {"pending", "running"}:
                job.status = "error"
                job.error = "interrupted by application restart"
                job.finished_at = _now()
                job.events.append(
                    {
                        "event": "error",
                        "message": job.error,
                        "at": job.finished_at,
                    }
                )
                interrupted = True
            self._jobs[job.id] = job
        if interrupted:
            self._save()

    def _save(self) -> None:
        atomic_write_json(
            self.path,
            {"version": 1, "jobs": [job.model_dump(mode="json") for job in self.list()]},
        )

    def start(
        self,
        job: Job,
        work: Callable[[], Awaitable[dict[str, Any]]],
    ) -> Job:
        async def runner() -> None:
            job.status = "running"
            job.started_at = _now()
            self._append_event(job, {"event": "running"})
            try:
                job.result = await work()
                job.status = "done"
                self._append_event(job, {"event": "completed"})
            except asyncio.CancelledError:
                job.status = "error"
                job.error = "cancelled"
                self._append_event(job, {"event": "error", "message": "cancelled"})
                raise
            except Exception as exc:
                job.status = "error"
                job.error = f"{type(exc).__name__}: {exc}"
                self._append_event(job, {"event": "error", "message": job.error})
            finally:
                job.finished_at = _now()
                self._tasks.pop(job.id, None)
                self._save()

        self._tasks[job.id] = asyncio.create_task(runner())
        return job

    def cancel(self, job_id: str) -> bool:
        task = self._tasks.get(job_id)
        if task is None:
            return False
        return task.cancel()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _default_jobs_path() -> Path:
    custom = os.getenv("PROMPT_SELECTOR_JOBS_PATH")
    if custom:
        return Path(custom).expanduser()
    return DEFAULT_JOBS_PATH
