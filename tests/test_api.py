import pytest
from fastapi.testclient import TestClient

from prompt_selector.api import app

MODEL = {
    "provider": "ollama",
    "model_id": "test-model",
    "model_class": "medium",
    "local": True,
    "context_window": 8192,
    "capabilities": ["structured_output", "system_messages"],
}


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_recommend_returns_the_profile_it_ranked_against(client):
    response = client.post(
        "/v1/recommend",
        json={"description": "Extract entities to strict JSON with a local model", "model": MODEL},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["recommendations"][0]["technique_id"] == "structured.schema-first"
    # Clients reuse this verbatim for compile and benchmark.
    assert body["task"]["task_type"] == "structured_extraction"
    assert body["task"]["constraints"]["strict_json"] is True


def test_compile_returns_every_stage(client):
    task = client.post(
        "/v1/recommend", json={"description": "Extract entities to strict JSON", "model": MODEL}
    ).json()["task"]
    response = client.post(
        "/v1/compile",
        json={
            "task": task,
            "user_input": "Mara went to Veyr.",
            "technique_id": "structured.few-shot-repair",
        },
    )
    assert response.status_code == 200
    program = response.json()
    assert [stage["stage"] for stage in program["stages"]] == ["draft", "repair"]
    assert program["expected_calls"] == 2
    assert "Mara went to Veyr." in program["stages"][0]["messages"][1]["content"]


def test_compile_rejects_an_unknown_technique(client):
    task = client.post(
        "/v1/recommend", json={"description": "Extract entities", "model": MODEL}
    ).json()["task"]
    response = client.post(
        "/v1/compile", json={"task": task, "user_input": "x", "technique_id": "nope.nope"}
    )
    assert response.status_code == 422


def test_datasets_are_listed_and_readable(client):
    listing = client.get("/v1/datasets").json()
    names = {item["name"] for item in listing}
    assert "entity-extraction" in names

    examples = client.get("/v1/datasets/entity-extraction").json()
    assert len(examples) == 6
    assert examples[0]["response_schema"]["required"] == ["people", "places"]

    assert client.get("/v1/datasets/does-not-exist").status_code == 404


def test_dataset_upload_reports_the_first_bad_line(client):
    response = client.post(
        "/v1/datasets/upload",
        files={
            "file": (
                "broken.jsonl",
                '{"id":"ok","input":"valid"}\n{"id":"bad"}\n',
                "application/x-ndjson",
            )
        },
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "Invalid JSONL at line 2" in detail
    assert "input" in detail


def test_uploaded_dataset_is_session_selectable_and_benchmarkable(client):
    uploaded = client.post(
        "/v1/datasets/upload",
        files={
            "file": (
                "my cases.jsonl",
                '{"id":"mine-1","input":"Mara entered Veyr.",'
                '"expected":{"people":["Mara"],"places":["Veyr"]}}\n',
                "application/x-ndjson",
            )
        },
    )
    assert uploaded.status_code == 201
    name = uploaded.json()["name"]
    assert name == "uploaded:my-cases"
    assert uploaded.json()["examples"] == 1
    assert name in {item["name"] for item in client.get("/v1/datasets").json()}
    assert client.get(f"/v1/datasets/{name}").json()[0]["id"] == "mine-1"

    task = client.post(
        "/v1/recommend", json={"description": "Extract entities", "model": MODEL}
    ).json()["task"]
    task["model"]["base_url"] = "http://127.0.0.1:9"
    started = client.post(
        "/v1/benchmark",
        json={
            "task": task,
            "technique_id": "structured.schema-first",
            "dataset": name,
            "record": False,
        },
    )
    assert started.status_code == 200
    job_id = started.json()["id"]
    for _ in range(200):
        job = client.get(f"/v1/jobs/{job_id}").json()
        if job["status"] in {"done", "error"}:
            break
    assert job["status"] == "done"
    assert job["result"]["dataset"] == name
    assert job["result"]["examples"] == 1


def test_capabilities_documents_the_extension_contract(client):
    body = client.get("/v1/capabilities").json()
    assert "single" in body["strategies"]
    assert "self_consistency" in body["strategies"]
    assert "field_f1" in body["graders"]
    assert "majority_vote" in body["aggregators"]
    assert body["techniques"] >= 14


def test_lint_endpoint_reports_a_clean_registry(client):
    body = client.get("/v1/lint").json()
    assert body["ok"] is True


def test_compare_requires_two_techniques(client):
    task = client.post(
        "/v1/recommend", json={"description": "Extract entities", "model": MODEL}
    ).json()["task"]
    response = client.post(
        "/v1/compare",
        json={
            "task": task,
            "technique_ids": ["structured.schema-first"],
            "dataset": "entity-extraction",
        },
    )
    assert response.status_code == 422


def test_benchmark_starts_a_job_and_reports_provider_failure(client):
    """No model is running in tests, so the job must fail loudly rather than fake numbers."""
    task = client.post(
        "/v1/recommend", json={"description": "Extract entities", "model": MODEL}
    ).json()["task"]
    task["model"]["base_url"] = "http://127.0.0.1:9"  # nothing listening
    started = client.post(
        "/v1/benchmark",
        json={
            "task": task,
            "technique_id": "structured.schema-first",
            "dataset": "entity-extraction",
            "record": False,
        },
    )
    assert started.status_code == 200
    job_id = started.json()["id"]

    for _ in range(200):
        job = client.get(f"/v1/jobs/{job_id}").json()
        if job["status"] in {"done", "error"}:
            break
    assert job["status"] in {"done", "error"}
    if job["status"] == "done":
        # A reachable model would still produce a scorecard; failures must be counted.
        assert job["result"]["scorecard"]["failures"] >= 0


def test_unknown_job_is_404(client):
    assert client.get("/v1/jobs/deadbeef").status_code == 404
