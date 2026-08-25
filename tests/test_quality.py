import json
import os
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from prompt_playoff.api import app
from prompt_playoff.domain import ModelResult
from prompt_playoff.evals import BenchmarkExample, ExampleRun, prompt_fingerprint
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
        build_dataset(DatasetBuildRequest(name="suite", description="Extract entities", count=3))
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
            example_id="a",
            repeat=0,
            output="",
            grades={"g": 1.0},
            latency_seconds=0,
            prompt_tokens=0,
            completion_tokens=0,
            calls=1,
        ),
        ExampleRun(
            example_id="b",
            repeat=0,
            output="",
            grades={"g": 0.2},
            latency_seconds=0,
            prompt_tokens=0,
            completion_tokens=0,
            calls=1,
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


def test_a_release_deleted_leaves_no_pointer_to_itself(tmp_path: Path):
    """The register erases where a business case archives.

    A case is what recorded runs are filed under, so erasing one strands their
    lineage; a release is a row about a prompt somebody froze, and the record of
    what shipped is the exported manifest in a repository. So a wrong row can
    go — but the row that replaced it cited it by id, and a citation pointing at
    nothing is the one fault this register exists to prevent.
    """
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
    assert second.previous_production_id == first.id

    removed = store.delete_release(first.id)

    assert removed.id == first.id
    remaining = store.releases()
    assert [item.id for item in remaining] == [second.id]
    assert remaining[0].previous_production_id is None


def test_deleting_a_release_is_refused_when_there_is_no_such_release(tmp_path: Path):
    store = QualityStore(tmp_path / "quality.json")
    with pytest.raises(ValueError, match="Unknown release"):
        store.delete_release("rel_nothing")


def test_a_deleted_release_takes_nothing_else_with_it(client: TestClient):
    """The run it cited is a measurement that happened, and still did."""
    created = client.post(
        "/v1/releases",
        json={"name": "throwaway", "technique_id": "direct", "prompt": {"text": "wrong"}},
    ).json()
    before = client.get("/v1/experiments").json()

    deleted = client.delete(f"/v1/releases/{created['id']}")

    assert deleted.status_code == 200
    assert deleted.json()["id"] == created["id"]
    assert all(item["id"] != created["id"] for item in client.get("/v1/releases").json())
    assert client.get("/v1/experiments").json() == before
    assert client.delete(f"/v1/releases/{created['id']}").status_code == 404


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


def test_registering_a_release_asks_nobody_to_approve_their_own_work(client: TestClient):
    """One user cannot be two, so a self-approval established nothing.

    Registering used to raise a review item asking the same person, at the same
    keyboard, to approve what they had just registered — and advancing was then
    refused until they clicked it. The queue's own guide already said approving
    there does not promote a release; the backend disagreed with it.
    """
    release = client.post(
        "/v1/releases",
        json={"name": "support", "technique_id": "direct", "prompt": {"text": "v1"}},
    ).json()
    assert [item for item in client.get("/v1/reviews").json() if item["kind"] == "release"] == []

    assert (
        client.post(f"/v1/releases/{release['id']}/action", json={"action": "test"}).status_code
        == 200
    )
    approved = client.post(f"/v1/releases/{release['id']}/action", json={"action": "approve"})
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
        json={
            "name": "from-failures",
            "description": "Classify support requests",
            "mode": "failures",
            "count": 4,
        },
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


def test_a_release_records_the_run_that_justified_it(client: TestClient):
    """Without this, "which numbers was this shipped on" is answered from memory.

    The field existed on the record and nothing ever filled it, so every release
    in the register looked equally unmeasured — including the ones that were not.
    """
    measured = client.post(
        "/v1/releases",
        json={
            "name": "support",
            "technique_id": "direct",
            "prompt": {"text": "v1"},
            "experiment_id": "abc123def456",
        },
    ).json()
    assert measured["experiment_id"] == "abc123def456"

    # A prompt nobody measured still registers — and says so, rather than being
    # indistinguishable from one that was.
    unmeasured = client.post(
        "/v1/releases",
        json={"name": "support", "technique_id": "direct", "prompt": {"text": "v2"}},
    ).json()
    assert unmeasured["experiment_id"] is None
    assert unmeasured["version"] == measured["version"] + 1


def _commit_thresholds(technique: str = "direct", quality_min: float = 0.85) -> None:
    """Write the project's committed bar where the release gate will read it."""
    Path(os.environ["PROMPT_PLAYOFF_CHECKS"]).write_text(
        f"""
version: 1
model:
  provider: ollama
  model_id: llama3.2:3b
checks:
  - name: shipping-bar
    technique: {technique}
    task: structured_extraction
    dataset: entity-extraction
    require:
      quality_min: {quality_min}
""",
        encoding="utf-8",
    )


RELEASED_PROMPT = {"text": "v1"}


def _record_a_run(
    quality: float, technique: str = "direct", measured: dict | None = RELEASED_PROMPT
) -> str:
    """A recorded run with a known quality, written where the store reads it.

    `measured` is the prompt the run is claimed to have measured; None stands for
    a run that measured no supplied prompt at all, which is what an older record
    looks like.
    """
    path = Path(os.environ["PROMPT_PLAYOFF_EXPERIMENTS_PATH"])
    record = {
        "id": "run00000001",
        "version": 1,
        "kind": "benchmark",
        "created_at": "2026-08-19T10:00:00+00:00",
        "provider": "ollama",
        "model_id": "test-model",
        "dataset": "entity-extraction",
        "technique_ids": [technique],
        "winner": technique,
        "metrics": {
            technique: {
                "quality": quality,
                "reliability": 1.0,
                "mean_latency_seconds": 0.5,
                "p95_latency_seconds": 0.9,
                "mean_total_tokens": 120.0,
                "runs": 10,
            }
        },
        "config_hash": "deadbeef",
        "authored_hash": prompt_fingerprint(measured) if measured is not None else None,
    }
    path.write_text(json.dumps({"experiments": [record]}), encoding="utf-8")
    return record["id"]


def test_a_release_below_the_committed_bar_cannot_be_approved(client: TestClient):
    """The thresholds guarded the repository and not the thing being shipped.

    `prompt-playoff.yaml` was enforced by CI alone, so a release could be waved
    through by hand at numbers the project had already declared unacceptable.
    """
    _commit_thresholds(quality_min=0.85)
    experiment = _record_a_run(quality=0.62)
    release = client.post(
        "/v1/releases",
        json={
            "name": "support",
            "technique_id": "direct",
            "prompt": {"text": "v1"},
            "experiment_id": experiment,
        },
    ).json()
    client.post(f"/v1/releases/{release['id']}/action", json={"action": "test"})

    gate = client.get(f"/v1/releases/{release['id']}/gate").json()
    assert gate["status"] == "failed"
    assert "quality 0.62 vs min 0.85" in gate["reason"]

    blocked = client.post(f"/v1/releases/{release['id']}/action", json={"action": "approve"})
    assert blocked.status_code == 409
    assert "0.85" in blocked.json()["detail"]


def test_a_release_over_the_committed_bar_advances_on_the_bar_alone(client: TestClient):
    """The committed thresholds are the whole gate.

    They are the same numbers `prompt-playoff check` enforces in CI, applied to
    the run this release cites — so clearing them here means clearing them there.
    A second click by the author never established that.
    """
    _commit_thresholds(quality_min=0.85)
    experiment = _record_a_run(quality=0.91)
    release = client.post(
        "/v1/releases",
        json={
            "name": "support",
            "technique_id": "direct",
            "prompt": {"text": "v1"},
            "experiment_id": experiment,
        },
    ).json()
    client.post(f"/v1/releases/{release['id']}/action", json={"action": "test"})
    assert client.get(f"/v1/releases/{release['id']}/gate").json()["status"] == "passed"

    approved = client.post(f"/v1/releases/{release['id']}/action", json={"action": "approve"})
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"


def test_a_release_with_a_bar_but_no_run_cannot_be_approved(client: TestClient):
    """A bar that cannot be applied is not a bar that was cleared."""
    _commit_thresholds(quality_min=0.85)
    release = client.post(
        "/v1/releases",
        json={"name": "support", "technique_id": "direct", "prompt": {"text": "v1"}},
    ).json()
    client.post(f"/v1/releases/{release['id']}/action", json={"action": "test"})

    blocked = client.post(f"/v1/releases/{release['id']}/action", json={"action": "approve"})
    assert blocked.status_code == 409
    assert "cites no recorded run" in blocked.json()["detail"]


def test_a_technique_with_no_committed_bar_advances_and_says_there_was_none(client: TestClient):
    """A project that never committed thresholds is recorded, not blocked.

    There is nothing to enforce, and inventing a bar would be worse than saying
    so. The gate says `not_configured` and the manifest hands over a `checks:`
    block to commit, which is the constructive answer to having no gate.
    """
    _commit_thresholds(technique="structured.schema-first")
    release = client.post(
        "/v1/releases",
        json={"name": "support", "technique_id": "direct", "prompt": {"text": "v1"}},
    ).json()
    client.post(f"/v1/releases/{release['id']}/action", json={"action": "test"})
    gate = client.get(f"/v1/releases/{release['id']}/gate").json()
    assert gate["status"] == "not_configured"
    assert "no bar to clear" in gate["reason"]

    approved = client.post(f"/v1/releases/{release['id']}/action", json={"action": "approve"})
    assert approved.status_code == 200


def test_a_release_may_not_ship_on_numbers_from_a_different_prompt(client: TestClient):
    """The citation was believed, not checked.

    Any experiment id was accepted beside any prompt, so a release could measure
    one text, freeze another, and read exactly like an honest one. The run now
    records the fingerprint of what it measured, and the two are compared.
    """
    _commit_thresholds(quality_min=0.85)
    # A run that scores well — on something else.
    experiment = _record_a_run(quality=0.99, measured={"text": "a different prompt"})
    release = client.post(
        "/v1/releases",
        json={
            "name": "support",
            "technique_id": "direct",
            "prompt": RELEASED_PROMPT,
            "experiment_id": experiment,
        },
    ).json()
    # Registering is still allowed: the register records what you decided, and
    # what the decision rests on.
    assert release["evidence"] == "indirect"
    client.post(f"/v1/releases/{release['id']}/action", json={"action": "test"})

    gate = client.get(f"/v1/releases/{release['id']}/gate").json()
    assert gate["status"] == "unverified"
    assert "measured a different prompt" in gate["reason"]
    blocked = client.post(f"/v1/releases/{release['id']}/action", json={"action": "approve"})
    assert blocked.status_code == 409


def test_a_release_citing_a_run_of_this_prompt_is_marked_measured(client: TestClient):
    experiment = _record_a_run(quality=0.91)
    release = client.post(
        "/v1/releases",
        json={
            "name": "support",
            "technique_id": "direct",
            "prompt": RELEASED_PROMPT,
            "experiment_id": experiment,
        },
    ).json()
    assert release["evidence"] == "measured"

    # An older record, from before runs carried a fingerprint, cannot be
    # confirmed either way — and unconfirmed is not confirmed.
    stale = _record_a_run(quality=0.91, measured=None)
    older = client.post(
        "/v1/releases",
        json={
            "name": "support",
            "technique_id": "direct",
            "prompt": RELEASED_PROMPT,
            "experiment_id": stale,
        },
    ).json()
    assert older["evidence"] == "indirect"

    no_citation = client.post(
        "/v1/releases",
        json={"name": "support", "technique_id": "direct", "prompt": RELEASED_PROMPT},
    ).json()
    assert no_citation["evidence"] == "unverified"


def test_a_release_registered_before_runs_were_recorded_can_be_given_its_evidence(
    client: TestClient,
):
    """Otherwise every version from before this existed is stranded for good.

    It cites nothing, so a project with a committed bar can never approve it,
    and measuring afterwards does not help — there was nowhere to put the run.
    """
    _commit_thresholds(quality_min=0.85)
    release = client.post(
        "/v1/releases",
        json={"name": "support", "technique_id": "direct", "prompt": RELEASED_PROMPT},
    ).json()
    assert release["evidence"] == "unverified"
    client.post(f"/v1/releases/{release['id']}/action", json={"action": "test"})

    experiment = _record_a_run(quality=0.91)
    cited = client.post(
        f"/v1/releases/{release['id']}/cite", json={"experiment_id": experiment}
    ).json()
    assert cited["evidence"] == "measured"
    assert client.get(f"/v1/releases/{release['id']}/gate").json()["status"] == "passed"


def test_citing_late_is_not_a_way_past_the_bar(client: TestClient):
    """The run is checked the same way, whenever it arrives."""
    _commit_thresholds(quality_min=0.85)
    release = client.post(
        "/v1/releases",
        json={"name": "support", "technique_id": "direct", "prompt": RELEASED_PROMPT},
    ).json()
    client.post(f"/v1/releases/{release['id']}/action", json={"action": "test"})

    elsewhere = _record_a_run(quality=0.99, measured={"text": "a different prompt"})
    cited = client.post(
        f"/v1/releases/{release['id']}/cite", json={"experiment_id": elsewhere}
    ).json()
    assert cited["evidence"] == "indirect"
    assert client.get(f"/v1/releases/{release['id']}/gate").json()["status"] == "unverified"

    assert (
        client.post(
            f"/v1/releases/{release['id']}/cite", json={"experiment_id": "nope"}
        ).status_code
        == 404
    )


def test_an_approved_release_keeps_the_run_it_was_approved_on(client: TestClient):
    """Swapping the evidence under a shipped version rewrites history."""
    experiment = _record_a_run(quality=0.91)
    release = client.post(
        "/v1/releases",
        json={
            "name": "support",
            "technique_id": "direct",
            "prompt": RELEASED_PROMPT,
            "experiment_id": experiment,
        },
    ).json()
    client.post(f"/v1/releases/{release['id']}/action", json={"action": "test"})
    client.post(f"/v1/releases/{release['id']}/action", json={"action": "approve"})

    refused = client.post(f"/v1/releases/{release['id']}/cite", json={"experiment_id": experiment})
    assert refused.status_code == 409
    assert "keeps the evidence it was approved on" in refused.json()["detail"]


def test_a_queue_written_by_an_older_version_still_opens(client: TestClient):
    """A file holding a retired kind is still the user's file.

    Releases used to raise approval items. Narrowing the kind without reading
    the old rows leniently turned every existing install's Reviews screen into
    a 500 on the first request.
    """
    from prompt_playoff.quality import QualityStore

    store = QualityStore(Path(os.environ["PROMPT_PLAYOFF_QUALITY"]))
    data = store._load_unlocked()
    data["reviews"].append(
        {
            "id": "review_rel_old",
            "kind": "release",
            "created_at": "2026-01-01T00:00:00Z",
            "title": "Approve release support v1",
            "status": "pending",
            "payload": {"release_id": "rel_old"},
        }
    )
    data["reviews"].append(
        {
            "id": "review_judge_1",
            "kind": "judge",
            "created_at": "2026-01-02T00:00:00Z",
            "title": "Confirm verdict",
            "status": "pending",
            "payload": {},
        }
    )
    store._save_unlocked(data)

    listed = client.get("/v1/reviews")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == ["review_judge_1"]

    # Answering the readable one leaves the retired row in the file rather than
    # quietly deleting history nobody asked to lose.
    client.post("/v1/reviews/review_judge_1", json={"action": "approve"})
    kinds = [item["kind"] for item in store._load_unlocked()["reviews"]]
    assert "release" in kinds


def test_the_review_queue_holds_only_what_a_model_asked_a_person(client: TestClient):
    """Reviews is for decisions a model could not make, not for self-approval."""
    from prompt_playoff.quality import ReviewItem

    kinds = ReviewItem.model_fields["kind"].annotation.__args__
    assert set(kinds) == {"dataset", "judge", "regression"}


def test_a_release_exports_a_manifest_and_a_checks_block_to_commit(client: TestClient):
    """The register stops being the record; the repository becomes it."""
    _commit_thresholds(quality_min=0.85)
    experiment = _record_a_run(quality=0.91)
    release = client.post(
        "/v1/releases",
        json={
            "name": "Support Desk",
            "technique_id": "direct",
            "prompt": RELEASED_PROMPT,
            "experiment_id": experiment,
        },
    ).json()

    manifest = client.get(f"/v1/releases/{release['id']}/manifest").json()
    assert manifest["filename"] == "support-desk-v1.release.json"
    assert manifest["checks_filename"] == "support-desk-v1.checks.yaml"

    document = json.loads(manifest["content"])
    assert document["prompt"]["fingerprint"] == release["prompt_hash"]
    assert document["evidence"]["verdict"] == "measured"
    assert document["evidence"]["experiment_id"] == experiment
    assert document["evidence"]["dataset_changed_since"] is False
    assert document["gate"]["status"] == "passed"

    # The checks file is the bar, in the shape `prompt-playoff check` reads.
    committed = yaml.safe_load(manifest["checks"])
    assert committed["checks"][0]["technique"] == "direct"
    assert committed["checks"][0]["require"]["quality_min"] == 0.85


def test_a_manifest_says_so_when_the_numbers_describe_another_prompt(client: TestClient):
    """A file that leaves the machine carries its own caveats or none survive."""
    _commit_thresholds(quality_min=0.85)
    experiment = _record_a_run(quality=0.99, measured={"text": "a different prompt"})
    release = client.post(
        "/v1/releases",
        json={
            "name": "support",
            "technique_id": "direct",
            "prompt": RELEASED_PROMPT,
            "experiment_id": experiment,
        },
    ).json()

    manifest = client.get(f"/v1/releases/{release['id']}/manifest").json()
    assert json.loads(manifest["content"])["evidence"]["verdict"] == "indirect"
    assert any("measured a different prompt" in note for note in manifest["notes"])


def test_a_manifest_separates_no_run_at_all_from_the_wrong_run(client: TestClient):
    """Unfinished work and a misattributed number are not the same warning."""
    release = client.post(
        "/v1/releases",
        json={"name": "support", "technique_id": "direct", "prompt": RELEASED_PROMPT},
    ).json()
    assert release["evidence"] == "unverified"

    notes = client.get(f"/v1/releases/{release['id']}/manifest").json()["notes"]
    assert any("cites no recorded run" in note for note in notes)
    assert not any("measured a different prompt" in note for note in notes)


def test_a_project_with_no_committed_bar_gets_one_to_paste(client: TestClient):
    _commit_thresholds(technique="structured.schema-first")
    release = client.post(
        "/v1/releases",
        json={"name": "support", "technique_id": "direct", "prompt": RELEASED_PROMPT},
    ).json()

    manifest = client.get(f"/v1/releases/{release['id']}/manifest").json()
    assert any("prompt-playoff.yaml" in note for note in manifest["notes"])
    committed = yaml.safe_load(manifest["checks"])
    assert committed["checks"][0]["name"] == "support-v1"
    assert committed["checks"][0]["require"] == {}


def test_a_bar_cleared_on_rows_that_have_since_changed_is_not_cleared(client: TestClient):
    """The numbers describe data that no longer exists."""
    _commit_thresholds(quality_min=0.85)
    experiment = _record_a_run(quality=0.91)
    # The run claims a revision of entity-extraction that does not match the set
    # this server can read, which is what an edited dataset looks like.
    path = Path(os.environ["PROMPT_PLAYOFF_EXPERIMENTS_PATH"])
    payload = json.loads(path.read_text())
    payload["experiments"][0]["dataset_revision"] = "a" * 64
    path.write_text(json.dumps(payload))

    release = client.post(
        "/v1/releases",
        json={
            "name": "support",
            "technique_id": "direct",
            "prompt": RELEASED_PROMPT,
            "experiment_id": experiment,
        },
    ).json()
    client.post(f"/v1/releases/{release['id']}/action", json={"action": "test"})

    gate = client.get(f"/v1/releases/{release['id']}/gate").json()
    assert gate["status"] == "stale"
    assert "no longer exist" in gate["reason"]
    blocked = client.post(f"/v1/releases/{release['id']}/action", json={"action": "approve"})
    assert blocked.status_code == 409


def test_judge_on_a_hundred_point_scale_is_read_not_refused(client: TestClient, monkeypatch):
    """A judge that answers 0-100 got the verdict right and the units wrong.

    The response schema asks for 0-10, and a model that ignored it used to take
    the whole request down with a 502 — deterministically for the same pair, so
    the retry that follows a 502 never helped. The verdict is the expensive
    part; the scale is arithmetic.
    """

    class HundredPointJudge:
        async def generate(self, prompt, model, timeout_seconds=120):
            assert "from 0 to 10" in prompt.messages[0].content
            return ModelResult(
                content='{"winner":"first","scores":{"first":80,"second":20},"rationale":"Fuller"}'
            )

    monkeypatch.setattr(app.state.service, "provider", lambda *args, **kwargs: HundredPointJudge())
    response = client.post(
        "/v1/evaluate/pairwise",
        json={
            "input": "Reply to the customer",
            "answer_a": "Steps",
            "answer_b": "A question",
            "rubric": ["Correctness"],
            "judge_model": {"provider": "ollama", "model_id": "judge"},
            "seed": 7,
        },
    )
    assert response.status_code == 200
    assert sorted(response.json()["scores"].values()) == [0.2, 0.8]


def test_judge_scales_stay_distinguishable(client: TestClient, monkeypatch):
    """0-1, 0-10 and 0-100 all land on 0-1 without colliding."""

    def judge_returning(first, second):
        class Judge:
            async def generate(self, prompt, model, timeout_seconds=120):
                return ModelResult(
                    content=f'{{"winner":"first","scores":{{"first":{first},'
                    f'"second":{second}}},"rationale":"r"}}'
                )

        return Judge()

    for first, second, expected in (
        (0.8, 0.2, [0.2, 0.8]),
        (8, 2, [0.2, 0.8]),
        (80, 20, [0.2, 0.8]),
    ):
        monkeypatch.setattr(
            app.state.service,
            "provider",
            lambda *args, _f=first, _s=second, **kwargs: judge_returning(_f, _s),
        )
        response = client.post(
            "/v1/evaluate/pairwise",
            json={
                "input": "in",
                "answer_a": "a",
                "answer_b": "b",
                "rubric": ["Correctness"],
                "judge_model": {"provider": "ollama", "model_id": "judge"},
                "seed": 7,
            },
        )
        assert response.status_code == 200, (first, second)
        assert sorted(response.json()["scores"].values()) == expected, (first, second)
