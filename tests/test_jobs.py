import asyncio
import json

import pytest

from prompt_playoff.jobs import JobStore


@pytest.mark.asyncio
async def test_completed_job_and_all_events_survive_restart(tmp_path):
    path = tmp_path / "jobs.json"
    store = JobStore(path)
    job = store.create("benchmark")
    store.note(job.id, {"completed": 1, "total": 2})

    async def work():
        store.note(job.id, {"completed": 2, "total": 2})
        return {"score": 1.0}

    store.start(job, work)
    await store._tasks[job.id]  # noqa: SLF001 - wait for the persisted lifecycle

    restored = JobStore(path).get(job.id)
    assert restored is not None
    assert restored.status == "done"
    assert restored.result == {"score": 1.0}
    assert [event.get("event") for event in restored.events] == [
        "queued",
        None,
        "running",
        None,
        "completed",
    ]
    assert restored.finished_at is not None


def test_running_job_is_marked_interrupted_after_restart(tmp_path):
    path = tmp_path / "jobs.json"
    store = JobStore(path)
    job = store.create("compare")
    job.status = "running"
    store._save()  # noqa: SLF001 - emulate a process stopping between events

    restored = JobStore(path).get(job.id)

    assert restored is not None
    assert restored.status == "error"
    assert restored.error == "interrupted by application restart"
    assert restored.events[-1]["message"] == restored.error


def test_corrupt_job_history_is_quarantined(tmp_path):
    path = tmp_path / "jobs.json"
    path.write_text('{"jobs":[', encoding="utf-8")

    store = JobStore(path)

    assert store.list() == []
    assert store.corrupt_path is not None
    assert store.corrupt_path.read_text(encoding="utf-8") == '{"jobs":['


def test_job_history_file_has_no_event_limit_by_default(tmp_path):
    path = tmp_path / "jobs.json"
    store = JobStore(path)
    job = store.create("optimize")

    for index in range(250):
        store.note(job.id, {"index": index})

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert len(payload["jobs"][0]["events"]) == 251


@pytest.mark.asyncio
async def test_cancelled_job_is_persisted(tmp_path):
    path = tmp_path / "jobs.json"
    store = JobStore(path)
    job = store.create("benchmark")

    async def work():
        await asyncio.Event().wait()
        return {}

    store.start(job, work)
    await asyncio.sleep(0)
    task = store._tasks[job.id]  # noqa: SLF001 - await cancellation persistence
    assert store.cancel(job.id) is True
    with pytest.raises(asyncio.CancelledError):
        await task

    restored = JobStore(path).get(job.id)
    assert restored is not None
    assert restored.status == "error"
    assert restored.error == "cancelled"
