from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from prompt_playoff.domain import MeasuredEvidence, TaskType
from prompt_playoff.engine import EngineCache
from prompt_playoff.measurements import MeasurementStore
from prompt_playoff.persistence import atomic_write_json


def _evidence(index: int) -> MeasuredEvidence:
    return MeasuredEvidence(
        technique_id=f"technique-{index}",
        task_type=TaskType.structured_extraction,
        provider="ollama",
        model_id="test",
        quality=1,
        reliability=1,
        mean_latency_seconds=0.1,
        mean_total_tokens=10,
        examples=1,
        repeats=1,
        dataset="parallel",
        recorded_at="2026-08-09T00:00:00+00:00",
    )


def test_measurement_store_preserves_all_concurrent_writers(tmp_path):
    path = tmp_path / "measurements.json"
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda index: MeasurementStore(path).record(_evidence(index)), range(24)))
    assert {item.technique_id for item in MeasurementStore(path).records} == {
        f"technique-{index}" for index in range(24)
    }


def test_engine_cache_preserves_all_concurrent_writers(tmp_path):
    path = tmp_path / "engine.json"
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda index: EngineCache(path).put(str(index), {"index": index}), range(24)))
    reloaded = EngineCache(path)
    assert [reloaded.get(str(index)) for index in range(24)] == [
        {"index": index} for index in range(24)
    ]


def test_atomic_write_failure_keeps_previous_good_content(tmp_path, monkeypatch):
    path = tmp_path / "store.json"
    atomic_write_json(path, {"previous": "good"})
    original = path.read_bytes()

    def fail_replace(source, destination):
        raise OSError("simulated crash before replace")

    monkeypatch.setattr("prompt_playoff.persistence.os.replace", fail_replace)
    with pytest.raises(OSError, match="simulated crash"):
        atomic_write_json(path, {"new": "incomplete"})
    assert path.read_bytes() == original
    assert json.loads(path.read_text()) == {"previous": "good"}


@pytest.mark.parametrize("store_type", [MeasurementStore, EngineCache])
def test_corrupt_files_are_quarantined_and_reported(tmp_path, store_type):
    path = tmp_path / "store.json"
    path.write_text('{"truncated":', encoding="utf-8")
    store = store_type(path)
    assert not path.exists()
    assert store.corrupt_path is not None
    assert store.corrupt_path.read_text(encoding="utf-8") == '{"truncated":'
    assert store.recovery_warning and ".corrupt-" in store.recovery_warning


def test_next_measurement_write_preserves_the_quarantined_bytes(tmp_path):
    path = tmp_path / "store.json"
    path.write_text('{"records":[', encoding="utf-8")
    store = MeasurementStore(path)
    quarantined = store.corrupt_path
    store.record(_evidence(1))
    assert MeasurementStore(path).records == [_evidence(1)]
    assert quarantined is not None
    assert quarantined.read_text(encoding="utf-8") == '{"records":['
