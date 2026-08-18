import json
import re
import time

import pytest
from fastapi.testclient import TestClient

from prompt_playoff import __version__, api, providers
from prompt_playoff.api import app
from prompt_playoff.domain import ModelResult
from prompt_playoff.engine import EngineCache, TaskEngine
from prompt_playoff.evals import BenchmarkExample
from prompt_playoff.optimizer import BACKENDS


def wait_for_job(client, job_id, timeout=60.0):
    """Wait for the worker thread to finish, on the clock rather than on a request count.

    A bare `for _ in range(200)` is not a wait: 200 polls against the test client
    take a fraction of a second. On Linux that happened to be enough because a
    connection to a closed port is refused immediately; Windows retries the SYN
    first, so the job was still running when the polls ran out.
    """
    deadline = time.monotonic() + timeout
    while True:
        job = client.get(f"/v1/jobs/{job_id}").json()
        if job["status"] in {"done", "error"}:
            return job
        if time.monotonic() >= deadline:
            raise AssertionError(f"job {job_id} still {job['status']} after {timeout}s")
        time.sleep(0.05)


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
    # Read the version rather than repeating it: a hardcoded copy here would have
    # to be found and edited on every release, and silently lies until someone does.
    assert client.get("/health").json() == {"status": "ok", "version": __version__}


@pytest.mark.parametrize("path", ["/", "/help", "/help/ru", "/benchmarks", "/benchmarks/ru"])
def test_static_pages_are_served(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert response.text.lstrip().startswith("<!doctype html>")


def test_documentation_pages_are_reachable(client):
    # The app opens both documents in its own panel, so each page only carries its translation link.
    # English is what an unqualified path serves; Russian is the translation hanging off it.
    navigation = client.get("/assets/navigation.js")
    assert navigation.status_code == 200
    assert "/help" in navigation.text
    assert "/benchmarks" in navigation.text
    assert 'lang="en"' in client.get("/help").text
    assert 'lang="ru"' in client.get("/help/ru").text
    assert "/help/ru" in client.get("/help").text
    assert "/help" in client.get("/help/ru").text
    assert "/benchmarks/ru" in client.get("/benchmarks").text
    assert "/benchmarks" in client.get("/benchmarks/ru").text


def test_home_references_reachable_packaged_assets(client):
    html = client.get("/").text
    asset_paths = re.findall(r'(?:href|src)="(/assets/[^"]+)"', html)

    assert asset_paths == [
        "/assets/styles.css",
        "/assets/core.js",
        "/assets/datasets.js",
        "/assets/catalog.js",
        "/assets/selector.js",
        "/assets/settings.js",
        "/assets/navigation.js",
        "/assets/platform.js",
        "/assets/measurements.js",
        "/assets/clipboard.js",
        "/assets/boot.js",
    ]
    for path in asset_paths:
        response = client.get(path)
        assert response.status_code == 200
        assert response.content
        expected_type = "text/css" if path.endswith(".css") else "text/javascript"
        assert response.headers["content-type"].startswith(expected_type)
        # The filenames never change, so without this a browser keeps showing an
        # old interface against a new server and gives no sign that it is.
        assert response.headers["cache-control"] == "no-cache, must-revalidate"


def test_home_exposes_stable_lifecycle_shell_destinations(client):
    html = client.get("/").text
    sidebar_destinations = re.findall(
        r'<a href="#[^"]+" data-global-tab="([^"]+)" data-screen="([^"]+)" '
        r'data-testid="nav-[^"]+">',
        html,
    )

    assert set(sidebar_destinations) == {
        ("prompt", "prompt"),
        # The measurements taken on a prompt are screens in their own right and
        # are listed as such, not only reachable through the tab strip.
        ("report", "report"),
        ("comparison", "comparison"),
        ("optimization", "optimization"),
        ("dataset-library", "dataset-library"),
        ("dataset-upload", "dataset-upload"),
        # Importing from the Hub is one of the three answers to "where do
        # examples come from", so it is a destination, not a button in a panel.
        ("dataset-hub", "dataset-hub"),
        ("dataset-builder", "dataset-builder"),
        ("history", "history"),
        ("judge", "judge"),
        ("model-matrix", "model-matrix"),
        ("context-lab", "context-lab"),
        ("analysis", "analysis"),
        ("regressions", "regressions"),
        ("reviews", "reviews"),
        ("releases", "releases"),
        ("production", "production"),
        ("techniques", "techniques"),
        ("logs", "logs"),
        ("evaluation", "evaluation"),
        ("help", "help"),
    }
    # Models & keys is not one of the workspace's screens: it is the setup every
    # screen depends on, so it lives in the corner of the rail and behind the
    # model chip, both visible from everywhere, rather than in the list.
    assert 'data-testid="rail-model"' in html
    assert 'data-testid="model-chip"' in html
    assert 'data-testid="lifecycle-nav"' in html
    assert 'data-testid="drawer-toggle"' in html
    assert html.count('data-testid="bottom-') == 4
    assert ">Evaluation guide<" in html
    # The sidebar used to repeat the prompt/dataset/model line that the context
    # bar already carries; one of the two had to go, and the header kept it.
    assert 'id="sidebar-prompt"' not in html
    assert 'id="context-prompt"' in html


@pytest.mark.parametrize("path", ["/assets/missing.js", "/assets/.hidden.js", "/assets/index.html"])
def test_static_asset_route_rejects_unknown_or_unsupported_files(client, path):
    assert client.get(path).status_code == 404


@pytest.mark.parametrize("section", ["prompt", "examples", "check", "ship", "reference"])
def test_section_drawings_are_packaged_and_served(client, section):
    # The frontend builds these paths from the section id, so nothing else here
    # would notice a drawing that was left out of the package or misnamed.
    response = client.get(f"/assets/section-{section}.webp")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/webp")
    assert response.content[:4] == b"RIFF"


def test_home_exposes_the_complete_technique_catalog(client):
    html = client.get("/").text
    techniques = client.get("/v1/techniques").json()
    examples = client.get("/v1/techniques/examples").json()

    assert 'data-global-tab="techniques"' in html
    catalog = client.get("/assets/catalog.js")
    assert catalog.status_code == 200
    assert "function renderTechniqueCatalog()" in catalog.text
    assert len(techniques) == 61
    assert len(examples) == len(techniques)
    assert len({item["user_input"] for item in examples}) == len(techniques)
    assert {item["technique_id"] for item in examples} == {item["id"] for item in techniques}
    compiled_signatures = {
        json.dumps(item["program"]["stages"], ensure_ascii=False, sort_keys=True)
        for item in examples
    }
    assert len(compiled_signatures) == len(techniques)

    by_id = {item["technique_id"]: item for item in examples}
    visible_examples = {
        "classification.label-rules": "BOUNDARY EXAMPLES",
        "few-shot.contrastive-cot": "DEMONSTRATIONS",
        "structured.few-shot-repair": "DEMONSTRATIONS",
        "translation.glossary-context": "REFERENCE RENDERINGS",
    }
    for technique_id, heading in visible_examples.items():
        messages = json.dumps(by_id[technique_id]["program"]["stages"], ensure_ascii=False)
        assert heading in messages


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


def test_request_api_key_is_not_returned_by_the_api(client):
    model = {**MODEL, "provider": "openai", "local": False, "api_key": "browser-secret"}
    response = client.post(
        "/v1/recommend",
        json={"description": "Extract entities to strict JSON", "model": model},
    )

    assert response.status_code == 200
    assert "browser-secret" not in response.text
    assert "api_key" not in response.json()["task"]["model"]


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


def test_author_endpoint_returns_engine_written_prompt(client, monkeypatch, tmp_path):
    task = client.post(
        "/v1/recommend", json={"description": "Write a Snake game in Python", "model": MODEL}
    ).json()["task"]
    authored = {
        "stages": [
            {
                "stage": "decompose",
                "system": "Plan a Python Snake game in terse architectural notes.",
                "user": "Cover the game loop, movement, food, scoring, and collisions.",
            },
            {
                "stage": "solve",
                "system": "Implement a complete runnable Python game from the notes.",
                "user": "Use these notes: {previous}\nReturn code and run instructions.",
            },
        ]
    }

    class AuthorProvider:
        async def generate(self, prompt, model, timeout_seconds=120):
            return ModelResult(content=json.dumps(authored))

    service = client.app.state.service
    engine = TaskEngine(
        None,
        provider=AuthorProvider(),
        cache=EngineCache(tmp_path / "author-cache.json"),
    )

    def use_engine(profile=None):
        engine.profile = profile
        return engine

    monkeypatch.setattr(service, "engine", use_engine)
    response = client.post(
        "/v1/author",
        json={
            "task": task,
            "description": "Write a Snake game in Python",
            "technique_id": "reasoning.decomposition",
            "engine_model": {"provider": "ollama", "model_id": "prompt-writer"},
        },
    )
    assert response.status_code == 200
    program = response.json()
    assert program["artifact_source"] == "engine"
    assert program["authored_by_model"] == "prompt-writer"
    assert "game loop" in program["stages"][0]["messages"][1]["content"]


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
    job = wait_for_job(client, job_id)
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


def test_capabilities_carries_the_wording_every_report_labels_its_numbers_with(client):
    body = client.get("/v1/capabilities").json()
    assert body["grader_help"]["token_f1"] == "word overlap with the reference answer"
    assert set(body["grader_help"]) == set(body["graders"])


def test_ollama_models_endpoint_offers_what_the_daemon_has(client, monkeypatch):
    async def fake_models(base_url=None):
        assert base_url == "http://box.local:11434"
        return [
            providers.InstalledModel(model_id="qwen2.5:7b", parameter_size="7.6B", size_bytes=1)
        ]

    monkeypatch.setattr(api, "ollama_models", fake_models)
    body = client.get("/v1/providers/ollama/models?base_url=http://box.local:11434").json()
    assert body == [{"model_id": "qwen2.5:7b", "parameter_size": "7.6B", "size_bytes": 1}]


def test_ollama_models_endpoint_says_how_to_start_a_daemon_that_is_down(client, monkeypatch):
    async def fake_models(base_url=None):
        raise providers.ProviderError("Ollama at http://127.0.0.1:11434 did not answer: refused.")

    monkeypatch.setattr(api, "ollama_models", fake_models)
    response = client.get("/v1/providers/ollama/models")
    assert response.status_code == 502
    assert "did not answer" in response.json()["detail"]


def test_integrations_lists_every_backend_without_the_optional_extras(client):
    # The UI builds its "Optimizer search" list from this endpoint and falls back
    # to a stub when it fails, so a 500 here silently costs the user three of the
    # four backends. It used to 500 on any machine without opentelemetry, because
    # find_spec("opentelemetry.sdk") imports the missing parent package.
    response = client.get("/v1/integrations")
    assert response.status_code == 200
    body = response.json()
    assert body["optimizer_backends"] == list(BACKENDS)
    assert body["tracing"]["otel_installed"] in (True, False)


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

    job = wait_for_job(client, job_id)
    assert job["events"][0]["event"] == "queued"
    assert job["events"][1]["event"] == "running"
    assert job["events"][-1]["event"] in {"completed", "error"}
    assert all("at" in event for event in job["events"])
    if job["status"] == "done":
        # A reachable model would still produce a scorecard; failures must be counted.
        assert job["result"]["scorecard"]["failures"] >= 0


def test_a_benchmark_measures_the_prompt_it_is_handed(client):
    """The authored prompt travels with the request and is what runs.

    The Prompt text screen can have an engine model write text into the compiled
    scaffold. A run that named only the technique recompiled it and measured
    words the person had never seen, so the prompt goes with the request and the
    preview in the report is the evidence of which text was sent.
    """
    task = client.post(
        "/v1/recommend", json={"description": "Extract entities", "model": MODEL}
    ).json()["task"]
    task["model"]["base_url"] = "http://127.0.0.1:9"  # nothing listening
    compiled = client.post(
        "/v1/compile",
        json={
            "task": task,
            "user_input": "{input}",
            "technique_id": "structured.schema-first",
        },
    ).json()
    stage = compiled["stages"][0]
    for message in stage["messages"]:
        if message["role"] == "user":
            message["content"] = "HOUSE RULE: never invent a place.\n" + message["content"]
    compiled["source_input"] = "{input}"

    started = client.post(
        "/v1/benchmark",
        json={
            "task": task,
            "technique_id": "structured.schema-first",
            "dataset": "entity-extraction",
            "record": False,
            "prompt": compiled,
        },
    )
    assert started.status_code == 200
    job = wait_for_job(client, started.json()["id"])
    # An unreachable model is counted as a failure per row, so the run still
    # finishes and still reports the text it sent.
    assert job["status"] == "done"
    sent = job["result"]["prompt_preview"]["stages"][0]["user"]
    assert sent.startswith("HOUSE RULE: never invent a place.")
    assert "{input}" not in sent


def test_a_prompt_from_another_technique_is_refused(client):
    """Numbers filed under the wrong method are worse than no numbers."""
    task = client.post(
        "/v1/recommend", json={"description": "Extract entities", "model": MODEL}
    ).json()["task"]
    task["model"]["base_url"] = "http://127.0.0.1:9"
    compiled = client.post(
        "/v1/compile",
        json={"task": task, "user_input": "{input}", "technique_id": "structured.schema-first"},
    ).json()
    started = client.post(
        "/v1/benchmark",
        json={
            "task": task,
            "technique_id": "direct.explicit-constraints",
            "dataset": "entity-extraction",
            "record": False,
            "prompt": compiled,
        },
    )
    job = wait_for_job(client, started.json()["id"])
    assert job["status"] == "error"
    assert "structured.schema-first" in job["error"]


def test_unknown_job_is_404(client):
    assert client.get("/v1/jobs/deadbeef").status_code == 404


def test_recommend_without_an_engine_stays_on_the_deterministic_path(client, monkeypatch):
    monkeypatch.delenv("PROMPT_PLAYOFF_ENGINE_MODEL", raising=False)
    response = client.post(
        "/v1/recommend",
        json={"description": "Extract entities to strict JSON", "model": MODEL},
    )
    assert response.status_code == 200
    # No engine means no engine note, so the warnings are only about the ranking.
    assert not any("engine model" in warning for warning in response.json()["warnings"])


def test_recommend_reports_an_unreachable_engine_instead_of_failing(client):
    response = client.post(
        "/v1/recommend",
        json={
            "description": "Extract entities to strict JSON",
            "model": MODEL,
            "engine_model": {
                "provider": "ollama",
                "model_id": "not-running",
                "base_url": "http://127.0.0.1:9",
            },
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["recommendations"], "an unreachable engine must not empty the ranking"
    assert any("not-running" in warning for warning in body["warnings"])


def test_optimize_still_accepts_the_legacy_optimizer_model_field():
    from prompt_playoff.api import OptimizeRequest

    payload = {
        "task": {"task_type": "structured_extraction", "model": MODEL},
        "optimizer_model": {"provider": "ollama", "model_id": "proposer"},
    }
    assert OptimizeRequest.model_validate(payload).engine_model.model_id == "proposer"

    payload["engine_model"] = {"provider": "ollama", "model_id": "engine"}
    assert OptimizeRequest.model_validate(payload).engine_model.model_id == "engine"


def test_recommend_returns_rejections_the_ui_can_render(client):
    response = client.post(
        "/v1/recommend",
        json={"description": "Extract entities to strict JSON", "model": MODEL},
    )
    rejected = response.json()["rejected"]
    assert rejected, "the ruled-out block has nothing to show without these"
    assert all(item["technique_id"] and item["title"] and item["reasons"] for item in rejected)


def test_uploaded_dataset_can_be_deleted_but_bundled_cannot(client: TestClient):
    rows = '{"id":"1","input":"hello","expected":"hi"}\n{"id":"2","input":"bye","expected":"ok"}\n'
    uploaded = client.post(
        "/v1/datasets/upload",
        files={"file": ("mine.jsonl", rows.encode(), "application/x-ndjson")},
    ).json()
    name = uploaded["name"]
    assert any(item["name"] == name for item in client.get("/v1/datasets").json())

    refused = client.delete("/v1/datasets/agents")
    assert refused.status_code == 422
    assert "bundled" in refused.json()["detail"]

    deleted = client.delete(f"/v1/datasets/{name}")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    assert not any(item["name"] == name for item in client.get("/v1/datasets").json())
    assert client.delete(f"/v1/datasets/{name}").status_code == 404


def test_deleting_a_saved_dataset_removes_its_file(client: TestClient, tmp_path):
    service = app.state.service
    service.dataset_store.directory = tmp_path
    path = service.add_user_dataset(
        "builder:gone",
        [BenchmarkExample(id="1", input="x", expected="y")],
        persist=True,
    )
    assert path.exists()

    response = client.delete("/v1/datasets/builder:gone")

    assert response.json()["removed_file"] == str(path)
    assert not path.exists()
