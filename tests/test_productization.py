from __future__ import annotations

import csv
import io
import json

import pytest
from fastapi.testclient import TestClient

from prompt_playoff.api import app
from prompt_playoff.deployment import export_runtime
from prompt_playoff.domain import ModelProfile, TaskProfile, TaskType
from prompt_playoff.evals import BenchmarkReport, Scorecard
from prompt_playoff.experiments import CSV_COLUMNS, ExperimentStore, experiments_csv
from prompt_playoff.model_profiles import ModelProfileStore


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def card(*, quality=0.8, latency=1.0, cost=0.002) -> Scorecard:
    return Scorecard(
        quality=quality,
        reliability=1.0,
        contract_pass_rate=1.0,
        stability=1.0,
        mean_latency_seconds=latency,
        p95_latency_seconds=latency,
        mean_total_tokens=100,
        mean_prompt_tokens=80,
        mean_completion_tokens=20,
        mean_calls=1,
        mean_cost_usd=cost,
        total_cost_usd=cost,
        runs=1,
    )


def report(scorecard: Scorecard) -> BenchmarkReport:
    return BenchmarkReport(
        technique_id="structured.schema-first",
        technique_title="Schema first",
        strategy="single",
        provider="openai",
        model_id="test-model",
        task_type="structured_extraction",
        dataset="cases",
        examples=1,
        repeats=1,
        started_at="2026-08-15T10:00:00+00:00",
        finished_at="2026-08-15T10:00:01+00:00",
        scorecard=scorecard,
        prompt_preview={"stages": [{"user": "Extract {input}"}]},
        dataset_revision="dataset-sha256",
        grader_version="graders-v2",
        seed_policy="repeat-index:0..0",
    )


def task() -> TaskProfile:
    return TaskProfile(
        task_type=TaskType.structured_extraction,
        model=ModelProfile(provider="openai", model_id="test-model", local=False),
    )


def test_saved_profiles_never_persist_request_keys(tmp_path):
    store = ModelProfileStore(tmp_path / "profiles.json")
    saved = store.save(
        "Production",
        ModelProfile(provider="openai", model_id="gpt-x", local=False, api_key="secret"),
    )

    assert saved.id == "production"
    assert "secret" not in (tmp_path / "profiles.json").read_text(encoding="utf-8")
    assert store.list()[0].profile.model_id == "gpt-x"


def test_experiment_history_versions_and_marks_degradation(tmp_path):
    store = ExperimentStore(tmp_path / "experiments.json")
    first = store.add_benchmark(report(card(quality=0.9, latency=0.8)), task())
    second = store.add_benchmark(report(card(quality=0.7, latency=1.1)), task())

    comparison = store.compare(first.id, second.id)

    assert (first.version, second.version) == (1, 2)
    assert first.task is not None
    assert first.task["model"]["model_id"] == "test-model"
    assert first.dataset_revision == "dataset-sha256"
    assert first.grader_version == "graders-v2"
    assert first.seed_policy == "repeat-index:0..0"
    assert first.prompt_snapshot == {"stages": [{"user": "Extract {input}"}]}
    assert first.prompt_snapshot_kind == "preview"
    assert first.environment["python"]
    by_metric = {item.metric: item for item in comparison.deltas}
    assert by_metric["quality"].degraded is True
    assert by_metric["mean_latency_seconds"].degraded is True


def test_prompt_snapshot_survives_store_restart_and_legacy_records_still_load(tmp_path):
    path = tmp_path / "experiments.json"
    store = ExperimentStore(path)
    recorded = store.add_benchmark(report(card()), task())

    restored = ExperimentStore(path).get(recorded.id)

    assert restored is not None
    assert restored.prompt_snapshot == {"stages": [{"user": "Extract {input}"}]}
    assert restored.prompt_snapshot_kind == "preview"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["experiments"][0].pop("prompt_snapshot")
    payload["experiments"][0].pop("prompt_snapshot_kind")
    path.write_text(json.dumps(payload), encoding="utf-8")
    legacy = ExperimentStore(path).get(recorded.id)
    assert legacy is not None
    assert legacy.prompt_snapshot is None
    assert legacy.prompt_snapshot_kind is None


def test_runtime_export_is_secret_free_and_preserves_server_orchestration():
    profile = ModelProfile(
        provider="openai", model_id="gpt-x", local=False, api_key="browser-secret"
    )
    bundle = export_runtime(
        task=TaskProfile(task_type=TaskType.summarization, model=profile),
        technique_id="reasoning.decomposition",
        language="python",
    )

    compile(bundle.content, bundle.filename, "exec")
    assert "/v1/run" in bundle.content
    assert "browser-secret" not in bundle.content
    assert json.loads(bundle.config)["technique_id"] == "reasoning.decomposition"


def test_profile_and_runtime_export_api(client):
    created = client.post(
        "/v1/model-profiles",
        json={
            "name": "Local fast",
            "profile": {"provider": "ollama", "model_id": "qwen", "api_key": "never-store"},
        },
    )
    assert created.status_code == 201
    assert "never-store" not in created.text
    assert client.get("/v1/model-profiles").json()[0]["id"] == "local-fast"

    exported = client.post(
        "/v1/export/runtime",
        json={
            "task": {"task_type": "summarization", "model": {"model_id": "qwen"}},
            "technique_id": "direct.explicit-constraints",
            "language": "typescript",
        },
    )
    assert exported.status_code == 200
    assert "runPromptPlayoff" in exported.json()["content"]


def test_history_csv_is_one_row_per_variant_with_unformatted_numbers(tmp_path):
    store = ExperimentStore(tmp_path / "experiments.json")
    store.add_benchmark(report(card(quality=0.8675, latency=0.79, cost=0.000000772)), task())

    text = experiments_csv(store.list())
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))

    assert text.startswith("﻿")  # or Excel reads the file in the legacy code page
    assert "\r\n" in text
    assert rows[0] == list(CSV_COLUMNS)
    assert len(rows) == 2
    row = dict(zip(CSV_COLUMNS, rows[1], strict=True))
    assert row["variant"] == "structured.schema-first"
    assert row["is_winner"] == "yes"
    # A spreadsheet has to read these as numbers, so no rounding and no "$".
    assert float(row["quality"]) == 0.8675
    assert float(row["mean_cost_usd"]) == 0.000000772
    assert row["kind"] == "benchmark"


def test_history_csv_neutralises_cells_a_spreadsheet_would_run(tmp_path):
    store = ExperimentStore(tmp_path / "experiments.json")
    hostile = task()
    hostile.model.model_id = '=HYPERLINK("http://evil","click")'
    store.add_benchmark(report(card()), hostile)

    row = list(csv.reader(io.StringIO(experiments_csv(store.list()).lstrip("﻿"))))[1]

    assert row[CSV_COLUMNS.index("model_id")].startswith("'=")


def test_history_csv_download_names_a_file(client):
    response = client.get("/v1/experiments.csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "prompt-playoff-history.csv" in response.headers["content-disposition"]
    assert response.text.lstrip("﻿").startswith("version,recorded_at,")
