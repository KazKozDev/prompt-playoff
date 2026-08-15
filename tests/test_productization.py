from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from prompt_playoff.api import app
from prompt_playoff.deployment import export_runtime
from prompt_playoff.domain import ModelProfile, TaskProfile, TaskType
from prompt_playoff.evals import BenchmarkReport, Scorecard
from prompt_playoff.experiments import ExperimentStore
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
    by_metric = {item.metric: item for item in comparison.deltas}
    assert by_metric["quality"].degraded is True
    assert by_metric["mean_latency_seconds"].degraded is True


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
