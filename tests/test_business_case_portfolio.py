from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from prompt_playoff.api import app
from prompt_playoff.business_cases import BusinessCaseStore
from prompt_playoff.domain import ModelProfile, TaskProfile, TaskType
from prompt_playoff.evals import BenchmarkReport, Scorecard
from prompt_playoff.experiments import ExperimentStore


def _score(quality: float = 0.8) -> Scorecard:
    return Scorecard(
        quality=quality,
        reliability=1.0,
        contract_pass_rate=1.0,
        stability=1.0,
        mean_latency_seconds=1.0,
        p95_latency_seconds=1.0,
        mean_total_tokens=100,
        mean_prompt_tokens=80,
        mean_completion_tokens=20,
        mean_calls=1,
        runs=1,
    )


def _report(prompt: str = "Extract {input}", dataset: str = "invoices") -> BenchmarkReport:
    return BenchmarkReport(
        technique_id="structured.schema-first",
        technique_title="Schema first",
        strategy="single",
        provider="openai",
        model_id="test-model",
        task_type="structured_extraction",
        dataset=dataset,
        examples=1,
        repeats=1,
        started_at="2026-08-23T10:00:00+00:00",
        finished_at="2026-08-23T10:00:01+00:00",
        scorecard=_score(),
        prompt_preview={"stages": [{"user": prompt}]},
        dataset_revision="dataset-sha256",
        grader_version="graders-v2",
        seed_policy="repeat-index:0..0",
    )


def _task() -> TaskProfile:
    return TaskProfile(
        task_type=TaskType.structured_extraction,
        model=ModelProfile(provider="openai", model_id="test-model", local=False),
    )


def test_business_case_store_keeps_archived_lineage(tmp_path):
    store = BusinessCaseStore(tmp_path / "business-cases.json")
    first = store.create("Invoice automation", "Extract invoice fields")
    second = store.create("Invoice automation", "A separate owner")

    assert first.id == "invoice-automation"
    assert second.id.startswith("invoice-automation-")

    renamed = store.update(first.id, name="Accounts payable", archived=True)

    assert renamed.name == "Accounts payable"
    assert store.list() == [second]
    assert {item.id for item in store.list(include_archived=True)} == {first.id, second.id}


def test_prompt_versions_are_scoped_to_the_business_case(tmp_path):
    cases = BusinessCaseStore(tmp_path / "business-cases.json")
    history = ExperimentStore(tmp_path / "experiments.json")
    invoices = cases.create("Invoice automation")
    support = cases.create("Support triage")

    first = history.add_benchmark(_report(), _task(), business_case=invoices)
    rerun = history.add_benchmark(_report(), _task(), business_case=invoices)
    rewrite = history.add_benchmark(
        _report(prompt="Return strict JSON for {input}"), _task(), business_case=invoices
    )
    other_case = history.add_benchmark(_report(), _task(), business_case=support)

    assert (first.prompt_version, rerun.prompt_version, rewrite.prompt_version) == (1, 1, 2)
    assert (first.version, rerun.version, rewrite.version) == (1, 2, 3)
    assert other_case.prompt_version == 1
    assert other_case.version == 1
    assert rewrite.business_case_name == "Invoice automation"
    assert rewrite.prompt_id == "structured.schema-first"

    with pytest.raises(ValueError, match="same business case"):
        history.compare(first.id, other_case.id)


def test_business_case_api_crud_and_archive(monkeypatch, tmp_path):
    monkeypatch.setenv("PROMPT_PLAYOFF_BUSINESS_CASES_PATH", str(tmp_path / "business-cases.json"))
    with TestClient(app) as client:
        created = client.post(
            "/v1/business-cases",
            json={"name": "Customer support", "description": "Route incoming tickets"},
        )
        assert created.status_code == 201
        case_id = created.json()["id"]

        updated = client.patch(f"/v1/business-cases/{case_id}", json={"name": "Support routing"})
        assert updated.status_code == 200
        assert updated.json()["name"] == "Support routing"
        assert client.get("/v1/business-cases").json()[0]["id"] == case_id

        archived = client.delete(f"/v1/business-cases/{case_id}")
        assert archived.status_code == 200
        assert archived.json()["archived"] is True
        assert client.get("/v1/business-cases").json() == []
        assert client.get("/v1/business-cases?include_archived=true").json()[0]["id"] == case_id


def test_measurement_rejects_unknown_or_archived_business_case(monkeypatch, tmp_path):
    monkeypatch.setenv("PROMPT_PLAYOFF_BUSINESS_CASES_PATH", str(tmp_path / "business-cases.json"))
    with TestClient(app) as client:
        payload = {
            "task": {"task_type": "structured_extraction", "model": {"model_id": "test"}},
            "technique_id": "structured.schema-first",
            "dataset": "entity-extraction",
            "business_case_id": "missing",
        }
        response = client.post("/v1/benchmark", json=payload)
        assert response.status_code == 422
        assert response.json()["detail"] == "Unknown business case"

        created = client.post("/v1/business-cases", json={"name": "Archived"}).json()
        client.delete(f"/v1/business-cases/{created['id']}")
        payload["business_case_id"] = created["id"]
        response = client.post("/v1/benchmark", json=payload)
        assert response.status_code == 422
        assert "archived" in response.json()["detail"]
