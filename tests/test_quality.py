from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from prompt_playoff.api import app
from prompt_playoff.domain import ModelResult
from prompt_playoff.evals import BenchmarkExample, ExampleRun
from prompt_playoff.quality import (
    DatasetBuildRequest,
    DatasetReviewRequest,
    DriftRequest,
    QualityStore,
    ReleaseActionRequest,
    ReleaseCreateRequest,
    build_dataset,
    confidence_interval,
    production_drift,
    security_suite,
    significance,
    slice_analysis,
)


def test_dataset_builder_is_seeded_and_keeps_truth_unreviewed():
    source = BenchmarkExample(id="real-1", input="Classify this ticket", expected="bug")
    payload = DatasetBuildRequest(
        name="Support robustness",
        description="Support classification",
        examples=[source],
        count=8,
        seed=42,
    )

    first = build_dataset(payload)
    second = build_dataset(payload)

    assert [item.example.input for item in first.examples] == [
        item.example.input for item in second.examples
    ]
    assert {item.status for item in first.examples} == {"unreviewed"}
    assert all(item.example.expected == "bug" for item in first.examples)
    assert any(item.split == "held-out" for item in first.examples)


def test_dataset_project_requires_explicit_approval(tmp_path: Path):
    store = QualityStore(tmp_path / "quality.json")
    project = store.add_dataset(
        build_dataset(
            DatasetBuildRequest(name="suite", description="Extract entities", count=3)
        )
    )
    assert not project.approved_examples

    reviewed = store.review_dataset(
        project.id,
        DatasetReviewRequest(example_ids=[project.examples[0].example.id], action="approve"),
    )
    assert len(reviewed.approved_examples) == 1


def test_confidence_and_significance_warn_on_small_samples():
    interval = confidence_interval([0.8, 0.9, 0.7])
    comparison = significance([0.1] * 40, [0.9] * 40)

    assert interval.warning
    assert comparison.significant is True
    assert comparison.direction == "improved"


def test_slice_analysis_exposes_weak_tags():
    examples = [
        BenchmarkExample(id="a", input="a", tags=["plain"]),
        BenchmarkExample(id="b", input="b", tags=["adversarial"]),
    ]
    runs = [
        ExampleRun(
            example_id="a", repeat=0, output="", grades={"g": 1.0},
            latency_seconds=0, prompt_tokens=0, completion_tokens=0, calls=1,
        ),
        ExampleRun(
            example_id="b", repeat=0, output="", grades={"g": 0.2},
            latency_seconds=0, prompt_tokens=0, completion_tokens=0, calls=1,
        ),
    ]
    result = slice_analysis(examples, runs)
    assert result[0].slice == "adversarial"
    assert result[0].quality == 0.2


def test_release_registry_enforces_lifecycle_and_rollback(tmp_path: Path):
    store = QualityStore(tmp_path / "quality.json")
    first = store.create_release(
        ReleaseCreateRequest(name="support", technique_id="direct", prompt={"text": "v1"})
    )
    for action in ("test", "approve", "release"):
        first = store.act_on_release(first.id, action)
    second = store.create_release(
        ReleaseCreateRequest(name="support", technique_id="direct", prompt={"text": "v2"})
    )
    for action in ("test", "approve", "release"):
        second = store.act_on_release(second.id, action)

    rolled_back = store.act_on_release(second.id, ReleaseActionRequest(action="rollback").action)
    assert rolled_back.id == first.id
    assert rolled_back.status == "production"


def test_drift_and_security_are_deterministic():
    report = production_drift(
        DriftRequest(
            baseline_inputs=["refund invoice billing"],
            current_inputs=["malware injection jailbreak"],
        )
    )
    cases = security_suite(BenchmarkExample(id="x", input="Summarize this"))

    assert report.alert is True
    assert len(cases) == 3
    assert all("security" in case.tags for case in cases)


def test_dataset_builder_api_publish_gate(client: TestClient):
    created = client.post(
        "/v1/dataset-projects",
        json={"name": "api-suite", "description": "Classify support requests", "count": 3},
    )
    assert created.status_code == 201
    project = created.json()
    assert client.post(f"/v1/dataset-projects/{project['id']}/publish").status_code == 422

    example_id = project["examples"][0]["example"]["id"]
    approved = client.post(
        f"/v1/dataset-projects/{project['id']}/review",
        json={"example_ids": [example_id], "action": "approve"},
    )
    assert approved.status_code == 200
    published = client.post(f"/v1/dataset-projects/{project['id']}/publish")
    assert published.status_code == 201
    assert published.json()["examples"] == 1


def test_pairwise_judge_is_blind_and_enters_review(client: TestClient, monkeypatch):
    class JudgeProvider:
        async def generate(self, prompt, model, timeout_seconds=120):
            assert "FIRST ANSWER" in prompt.messages[1].content
            assert "Answer A" not in prompt.messages[1].content
            return ModelResult(
                content='{"winner":"first","scores":{"first":9,"second":4},'
                '"rationale":"More accurate"}'
            )

    monkeypatch.setattr(app.state.service, "provider", lambda *args, **kwargs: JudgeProvider())
    response = client.post(
        "/v1/evaluate/pairwise",
        json={
            "input": "Summarize the incident",
            "answer_a": "Short answer",
            "answer_b": "Long answer",
            "rubric": ["Correctness"],
            "judge_model": {"provider": "ollama", "model_id": "judge"},
            "seed": 7,
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "pending_human_review"
    assert sorted(response.json()["scores"].values()) == [0.4, 0.9]
    reviews = client.get("/v1/reviews").json()
    assert reviews[0]["kind"] == "judge"
    assert reviews[0]["status"] == "pending"


def test_release_api_requires_human_review_before_approval(client: TestClient):
    release = client.post(
        "/v1/releases",
        json={"name": "support", "technique_id": "direct", "prompt": {"text": "v1"}},
    ).json()
    assert client.post(
        f"/v1/releases/{release['id']}/action", json={"action": "test"}
    ).status_code == 200
    blocked = client.post(
        f"/v1/releases/{release['id']}/action", json={"action": "approve"}
    )
    assert blocked.status_code == 409

    review = next(
        item for item in client.get("/v1/reviews").json() if item["kind"] == "release"
    )
    client.post(f"/v1/reviews/{review['id']}", json={"action": "approve"})
    approved = client.post(
        f"/v1/releases/{release['id']}/action", json={"action": "approve"}
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
