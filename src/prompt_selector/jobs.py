"""In-process job queue for work that takes real model calls.

Benchmarks and optimization runs take minutes, so the HTTP layer starts them as
jobs and the client polls. Deliberately simple: one process, no broker.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


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
    def __init__(self, max_events: int = 200) -> None:
        self._jobs: dict[str, Job] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self.max_events = max_events

    def create(self, kind: str) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind, created_at=_now())
        self._jobs[job.id] = job
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
        job.events.append({**event, "at": _now()})
        if len(job.events) > self.max_events:
            del job.events[: len(job.events) - self.max_events]

    def start(
        self,
        job: Job,
        work: Callable[[], Awaitable[dict[str, Any]]],
    ) -> Job:
        async def runner() -> None:
            job.status = "running"
            job.started_at = _now()
            try:
                job.result = await work()
                job.status = "done"
            except asyncio.CancelledError:
                job.status = "error"
                job.error = "cancelled"
                raise
            except Exception as exc:
                job.status = "error"
                job.error = f"{type(exc).__name__}: {exc}"
            finally:
                job.finished_at = _now()
                self._tasks.pop(job.id, None)

        self._tasks[job.id] = asyncio.create_task(runner())
        return job

    def cancel(self, job_id: str) -> bool:
        task = self._tasks.get(job_id)
        if task is None:
            return False
        return task.cancel()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
