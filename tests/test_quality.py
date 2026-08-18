from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from prompt_playoff.api import app
from prompt_playoff.domain import ModelResult
from prompt_playoff.evals import BenchmarkExample, ExampleRun
from prompt_playoff.quality import (
    MUTATION_INTENT,
    DatasetBuildRequest,
    DatasetReviewRequest,
    DriftRequest,
    ManagedExample,
    QualityStore,
    ReleaseActionRequest,
    ReleaseCreateRequest,
    apply_similarity,
    build_dataset,
    confidence_interval,
    data_mix,
    production_drift,
    security_suite,
    shares_family,
    significance,
    slice_analysis,
    verify_examples,
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


def test_checks_object_before_a_person_has_to():
    source = BenchmarkExample(id="real-1", input="line one\nline two", expected="bug")
    project = build_dataset(
        DatasetBuildRequest(
            name="flagged", description="Classify tickets", examples=[source], count=8, seed=3
        )
    )
    codes = {check.code for item in project.examples for check in item.checks}

    assert "stale-answer" in codes
    flagged = [item for item in project.examples if item.checks]
    assert flagged and all(item.review_priority[0] == 0 for item in flagged)


def test_coverage_keeps_the_empty_axes():
    project = build_dataset(
        DatasetBuildRequest(name="thin", description="Extract entities", count=3, seed=11)
    )
    empty = [cell.axis for cell in project.coverage if not cell.examples]

    assert len(project.coverage) > 3
    assert empty and all(MUTATION_INTENT[axis] for axis in empty)


def test_low_agreement_is_flagged_and_families_are_compared():
    items = verify_examples(
        [
            ManagedExample(
                example=BenchmarkExample(id="a", input="x", expected="maybe"),
                agreement=0.25,
            )
        ]
    )

    assert [check.code for check in items[0].checks] == ["low-agreement"]
    assert shares_family("qwen3:8b", "qwen3:32b") is True
    assert shares_family("qwen3:8b", "llama3.2:3b") is False


def test_near_duplicates_are_flagged_with_the_number_that_flagged_them():
    """The rule the exact-match one cannot state: same row, different wording."""
    items = [
        ManagedExample(example=BenchmarkExample(id="a", input="Please cancel my subscription")),
        ManagedExample(
            example=BenchmarkExample(id="b", input="I would like to cancel my subscription")
        ),
        ManagedExample(example=BenchmarkExample(id="c", input="My package has not arrived")),
    ]
    # Stand-in vectors: a and b almost parallel, c pointing elsewhere.
    vectors = [[1.0, 0.0], [0.97, 0.24], [0.0, 1.0]]

    diversity = apply_similarity(items, vectors, threshold=0.9)

    assert [check.code for check in items[1].checks] == ["near-duplicate"]
    assert "a" in items[1].checks[0].detail
    # The number is in the objection: the threshold is a calibration, so a
    # reader has to be able to disagree with it.
    assert "%" in items[1].checks[0].detail
    assert not items[0].checks and not items[2].checks
    assert diversity is not None and 0.0 < diversity < 1.0


def test_similarity_says_nothing_when_there_is_nothing_to_compare():
    single = [ManagedExample(example=BenchmarkExample(id="a", input="only row"))]

    assert apply_similarity(single, [[1.0, 0.0]]) is None
    # A vector per row or no verdict at all: a half-embedded set would flag rows
    # by comparing them with whatever happened to line up.
    assert apply_similarity(single * 2, [[1.0, 0.0]]) is None


def test_an_exact_duplicate_is_not_also_reported_as_a_near_one():
    items = verify_examples(
        [
            ManagedExample(example=BenchmarkExample(id="a", input="cancel my plan")),
            ManagedExample(example=BenchmarkExample(id="b", input="Cancel my plan")),
        ]
    )
    apply_similarity(items, [[1.0, 0.0], [1.0, 0.0]], threshold=0.9)

    assert [check.code for check in items[1].checks] == ["duplicate-input"]


def test_failure_mode_needs_the_rows_it_builds_around(client: TestClient):
    refused = client.post(
        "/v1/dataset-projects",
        json={"name": "from-failures", "description": "Classify support requests",
              "mode": "failures", "count": 4},
    )
    assert refused.status_code == 422

    built = client.post(
        "/v1/dataset-projects",
        json={
            "name": "from-failures",
            "description": "Classify support requests",
            "mode": "failures",
            "count": 4,
            "examples": [{"id": "missed-1", "input": "It broke again", "expected": "bug"}],
        },
    )
    assert built.status_code == 201
    project = built.json()
    assert project["examples"][0]["mutation"] == "as_failed"
    assert project["examples"][0]["example"]["input"] == "It broke again"
    assert all("from-failure" in item["example"]["tags"] for item in project["examples"])


def test_judge_warns_when_it_shares_a_family_with_the_answers(client: TestClient, monkeypatch):
    class JudgeProvider:
        async def generate(self, prompt, model, timeout_seconds=120):
            return ModelResult(
                content='{"winner":"first","scores":{"first":9,"second":4},"rationale":"ok"}'
            )

    monkeypatch.setattr(app.state.service, "provider", lambda *args, **kwargs: JudgeProvider())
    body = {
        "input": "Summarize the incident",
        "answer_a": "Short",
        "answer_b": "Long",
        "rubric": ["Correctness"],
        "judge_model": {"provider": "ollama", "model_id": "qwen3:32b"},
        "subject_models": ["qwen3:8b"],
    }
    same = client.post("/v1/evaluate/pairwise", json=body).json()
    other = client.post(
        "/v1/evaluate/pairwise", json={**body, "subject_models": ["llama3.2:3b"]}
    ).json()

    assert "same model family" in same["self_preference_warning"]
    assert other["self_preference_warning"] is None


def test_data_mix_names_a_fully_generated_set():
    generated = data_mix([BenchmarkExample(id="a", input="a", tags=["synthetic"])])
    observed = data_mix([BenchmarkExample(id="b", input="b", tags=["production"])])

    assert generated.synthetic_ratio == 1.0
    assert "written by a model" in generated.note
    assert observed.synthetic == 0
