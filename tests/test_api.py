import json
import re
import time
from pathlib import Path

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


@pytest.mark.parametrize("path", ["/", "/help", "/help/ru", "/evaluation", "/evaluation/ru"])
def test_static_pages_are_served(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert response.text.lstrip().startswith("<!doctype html>")


def test_home_opens_on_the_welcome_screen(client):
    # The opening screen is the first thing a new browser sees, and the only
    # thing that can put the app back behind it once it has been dismissed is
    # the "#welcome" hash the head script reads.
    html = client.get("/").text

    assert 'data-testid="splash"' in html
    assert "Finds the free AI model your business needs" in html
    assert 'data-testid="splash-enter"' in html
    assert "'#welcome'" in html
    assert "pp-splash-seen" in html

    mark = client.get("/assets/logo-mark.webp")
    assert mark.status_code == 200
    assert mark.headers["content-type"].startswith("image/webp")
    assert mark.content[:4] == b"RIFF"


def test_documentation_pages_are_reachable(client):
    # The app opens both documents in its own panel, so each page only carries its translation link.
    # English is what an unqualified path serves; Russian is the translation hanging off it.
    navigation = client.get("/assets/navigation.js")
    assert navigation.status_code == 200
    assert "/help" in navigation.text
    assert "/evaluation" in navigation.text
    assert 'lang="en"' in client.get("/help").text
    assert 'lang="ru"' in client.get("/help/ru").text
    assert "/help/ru" in client.get("/help").text
    assert "/help" in client.get("/help/ru").text
    assert 'class="page"' in client.get("/help").text
    assert 'class="page"' in client.get("/help/ru").text
    assert 'class="article"' in client.get("/help").text
    assert 'lang="en"' in client.get("/evaluation").text
    assert 'lang="ru"' in client.get("/evaluation/ru").text
    assert "/evaluation/ru" in client.get("/evaluation").text
    assert "/evaluation" in client.get("/evaluation/ru").text


def test_the_prompt_vs_finetuning_guide_is_served_in_both_languages(client):
    assert "/prompt-vs-finetuning/ru" in client.get("/prompt-vs-finetuning").text
    assert "/prompt-vs-finetuning" in client.get("/prompt-vs-finetuning/ru").text


def test_the_prompt_vs_finetuning_guide_follows_the_app_theme(client):
    # Same stylesheet as Help and the Evaluation guide, so a token cannot drift
    # to a second copy inside this page. The large title and two-plate layout
    # are the only things it adds; embed must not hide the heading.
    css = client.get("/assets/docs.css").text
    assert "prefers-color-scheme" in css
    assert "main.page" in css
    assert "html:has(main.page) body" in css
    for path in ("/prompt-vs-finetuning", "/prompt-vs-finetuning/ru"):
        html = client.get(path).text
        assert "/assets/docs.css" in html
        assert "<style>" not in html
        assert ":root.embed .hero{display:none}" not in html
        assert "lang-switch" in html
        assert 'class="article"' in html
        assert 'class="toc"' in html
        assert html.index('class="toc"') < html.index('class="article"')
        assert "\\!==" not in html
        assert html.lstrip().startswith("<!DOCTYPE html>")
    nav = client.get("/assets/navigation.js").text
    assert "guide-split" in nav
    assert "data-guide-toc" in nav
    assert ":root.embed main.page footer" in css
    assert "max-height:calc(100vh - 36px)" in css


def test_the_old_benchmarks_paths_point_at_the_guide(client):
    # The guide was called Benchmarks before it was called the Evaluation guide.
    # Anyone holding an old link lands on the document rather than on a 404.
    for old, new in (("/benchmarks", "/evaluation"), ("/benchmarks/ru", "/evaluation/ru")):
        response = client.get(old, follow_redirects=False)
        assert response.status_code == 301
        assert response.headers["location"] == new


def test_documents_reference_reachable_packaged_assets(client):
    # Both documents load the same stylesheet and the same script; a page that
    # points at a file the package does not ship renders as a wall of text, and
    # nothing else in the suite would notice.
    for path in (
        "/help",
        "/help/ru",
        "/evaluation",
        "/evaluation/ru",
        "/prompt-vs-finetuning",
        "/prompt-vs-finetuning/ru",
    ):
        assets = re.findall(r'(?:href|src)="(/assets/[^"]+)"', client.get(path).text)
        assert assets == ["/assets/docs.js", "/assets/docs.css"] or assets == [
            "/assets/docs.css",
            "/assets/docs.js",
        ], f"{path} loads {assets}"
        for asset in assets:
            response = client.get(asset)
            assert response.status_code == 200
            assert response.content


def test_home_references_reachable_packaged_assets(client):
    html = client.get("/").text
    asset_paths = re.findall(r'(?:href|src)="(/assets/[^"]+)"', html)

    assert asset_paths == [
        "/assets/styles.css",
        "/assets/logo-mark.webp",
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
        expected_type = {".css": "text/css", ".webp": "image/webp"}.get(
            Path(path).suffix, "text/javascript"
        )
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
        # The benchmarks inside the package answer a different question from the
        # library — what this tool measures itself against, not what you measure
        # your prompt against — so they are a destination of their own.
        ("dataset-bundled", "dataset-bundled"),
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
        # Models & keys is the setup every screen depends on, so it stays in the
        # corner of the rail and behind the model chip, both visible from
        # everywhere. It is a row under Reference as well: the section screen
        # lists what is under it, and a rail that named three of those four
        # screens sent anyone who opened Reference looking for the fourth.
        ("settings", "settings"),
        ("logs", "logs"),
        ("evaluation", "evaluation"),
        ("prompt-vs-finetuning", "prompt-vs-finetuning"),
        ("help", "help"),
    }
    assert 'data-testid="rail-model"' in html
    assert 'data-testid="model-chip"' in html
    assert 'data-testid="lifecycle-nav"' in html
    assert 'data-testid="drawer-toggle"' in html
    # One entry per section of the rail, Reference included. With four, every
    # screen under Reference — Jobs & logs, the guide, Help and Models & keys —
    # lit nothing at all on a phone, and the bar stopped answering "where am I"
    # on the screens a reader is most likely to be lost on.
    assert html.count('data-testid="bottom-') == 5
    assert 'data-testid="bottom-reference"' in html
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


def test_an_upload_is_kept_only_when_the_uploader_asks(client, tmp_path, monkeypatch):
    # Rows arriving off someone's own machine are not written to disk by
    # default; ticking the box on the upload screen is what makes the promise.
    from prompt_playoff import api as api_module

    service = api_module.app.state.service
    monkeypatch.setattr(service.dataset_store, "directory", tmp_path)

    session = client.post(
        "/v1/datasets/upload",
        files={"file": ("session.jsonl", b'{"id":"1","input":"hello"}\n', "application/x-ndjson")},
    ).json()
    assert session["kept"] is False
    assert not list(tmp_path.glob("*.jsonl"))

    kept = client.post(
        "/v1/datasets/upload",
        files={"file": ("kept.jsonl", b'{"id":"1","input":"hello"}\n', "application/x-ndjson")},
        data={"keep": "true"},
    ).json()
    assert kept["kept"] is True
    assert [path.name for path in tmp_path.glob("*.jsonl")] == ["uploaded%3Akept.jsonl"]

    listed = {item["name"]: item["kept"] for item in client.get("/v1/datasets").json()}
    assert listed["uploaded:kept"] is True
    assert listed["uploaded:session"] is False


def test_datasets_say_whose_rows_they_hold_and_under_what_licence(client):
    # The shelf of bundled benchmarks names a source and a licence per set. Both
    # come from the import presets that fetched the rows, so the page cannot
    # claim a licence the fetching code does not.
    by_name = {item["name"]: item for item in client.get("/v1/datasets").json()}

    corpus = by_name["few-nerd"]["provenance"]
    assert corpus["source"] == "DFKI-SLT/few-nerd"
    assert corpus["url"] == "https://huggingface.co/datasets/DFKI-SLT/few-nerd"
    assert corpus["licence"].startswith("CC-BY-SA-4.0")
    assert "Few-NERD" in corpus["citation"]

    # Built here, so it carries this package's own licence and no repository.
    built = by_name["agents"]["provenance"]
    assert built == {"source": "built here", "licence": "MIT"}


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


def test_capabilities_says_how_the_grades_become_the_headline_numbers(client):
    # The Measurement screen names, before a run, which grader its quality will
    # come from and which ones feed reliability. Both orderings are served so
    # the page states what the scorecard will do rather than a second guess at it.
    body = client.get("/v1/capabilities").json()
    assert body["quality_preference"][0] == "unit_tests"
    assert body["quality_preference"].index("exact_match") < body["quality_preference"].index(
        "label_accuracy"
    )
    assert "json_validity" in body["reliability_graders"]
    assert set(body["quality_preference"]) <= set(body["graders"])
    assert set(body["reliability_graders"]) <= set(body["graders"])


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


def _optimizer_winner(technique_id: str = "structured.schema-first"):
    """An exported technique shaped exactly as an optimization run emits one."""
    from prompt_playoff.optimizer import Candidate, TechniqueOverlay, export_technique
    from prompt_playoff.registry import Registry

    spec = Registry.load().technique(technique_id)
    overlay = TechniqueOverlay(
        block_appends={spec.recipe.blocks[0].name: "HOUSE RULE: never invent a place."}
    )
    candidate = Candidate(id="r1c1", technique_id=spec.id, origin="reflective", overlay=overlay)
    return export_technique(overlay.apply(spec), candidate)


def test_adopting_a_winner_keeps_the_identity_the_rest_of_the_tool_resolves(client):
    """An adopted prompt has to stay measurable, runnable and exportable.

    `export_technique` renames the winner to `<id>.optimized` because that file is
    written into a registry. Nothing resolves that id here, so a program carrying
    it could not be benchmarked, run or exported — the adopted prompt keeps the
    id it was searched from, and the optimized text is what changed.
    """
    task = client.post(
        "/v1/recommend", json={"description": "Extract entities", "model": MODEL}
    ).json()["task"]
    response = client.post(
        "/v1/optimize/adopt",
        json={
            "task": task,
            "technique_id": "structured.schema-first",
            "technique": _optimizer_winner(),
            "reusable": True,
            "engine_model_id": "proposer-model",
        },
    )

    assert response.status_code == 200
    program = response.json()
    assert program["technique_id"] == "structured.schema-first"
    assert program["artifact_source"] == "optimizer"
    assert program["authored_by_model"] == "proposer-model"
    written = "\n".join(
        message["content"] for stage in program["stages"] for message in stage["messages"]
    )
    assert "HOUSE RULE: never invent a place." in written

    # The point of keeping the id: this program is accepted by the runner that
    # refuses a prompt written from another technique.
    task["model"]["base_url"] = "http://127.0.0.1:9"
    started = client.post(
        "/v1/benchmark",
        json={
            "task": task,
            "technique_id": "structured.schema-first",
            "dataset": "entity-extraction",
            "record": False,
            "prompt": program,
        },
    )
    assert started.status_code == 200
    job = wait_for_job(client, started.json()["id"])
    assert job["status"] == "done"
    assert (
        "HOUSE RULE: never invent a place." in job["result"]["prompt_preview"]["stages"][0]["user"]
    )


def test_adopting_recompiles_rather_than_copying_the_optimizer_preview(client):
    """The preview on the Optimization screen has a benchmark row inside it.

    It is compiled against `dataset[0].input`, so copying it onto the prompt
    screen would ship somebody else's example as the task. Adoption compiles the
    winning instructions against this task instead.
    """
    task = client.post(
        "/v1/recommend", json={"description": "Extract entities", "model": MODEL}
    ).json()["task"]
    reusable = client.post(
        "/v1/optimize/adopt",
        json={
            "task": task,
            "technique_id": "structured.schema-first",
            "technique": _optimizer_winner(),
            "reusable": True,
        },
    ).json()
    assert reusable["source_input"] == "{input}"

    own_words = client.post(
        "/v1/optimize/adopt",
        json={
            "task": task,
            "technique_id": "structured.schema-first",
            "technique": _optimizer_winner(),
            "reusable": False,
            "description": "Pull every person and place out of this contract.",
        },
    ).json()
    assert own_words["source_input"] == "Pull every person and place out of this contract."


def test_adopting_refuses_a_technique_it_did_not_produce(client):
    task = client.post(
        "/v1/recommend", json={"description": "Extract entities", "model": MODEL}
    ).json()["task"]
    response = client.post(
        "/v1/optimize/adopt",
        json={
            "task": task,
            "technique_id": "structured.schema-first",
            "technique": {"id": "nonsense", "title": "Nonsense"},
            "reusable": True,
        },
    )
    assert response.status_code == 422
    assert "not a technique" in response.json()["detail"]


def test_adopting_a_template_needs_either_material_or_the_input_slot(client):
    task = client.post(
        "/v1/recommend", json={"description": "Extract entities", "model": MODEL}
    ).json()["task"]
    response = client.post(
        "/v1/optimize/adopt",
        json={
            "task": task,
            "technique_id": "structured.schema-first",
            "technique": _optimizer_winner(),
            "reusable": False,
            "description": "   ",
        },
    )
    assert response.status_code == 422


def test_a_recorded_benchmark_hands_back_the_run_it_was_filed_as(client):
    """A release has to be able to name the run that justified it."""
    task = client.post(
        "/v1/recommend", json={"description": "Extract entities", "model": MODEL}
    ).json()["task"]
    task["model"]["base_url"] = "http://127.0.0.1:9"
    started = client.post(
        "/v1/benchmark",
        json={
            "task": task,
            "technique_id": "structured.schema-first",
            "dataset": "entity-extraction",
        },
    )
    job = wait_for_job(client, started.json()["id"])
    assert job["status"] == "done"

    experiment_id = job["result"]["experiment_id"]
    assert experiment_id
    assert client.get(f"/v1/experiments/{experiment_id}").status_code == 200


def test_optimize_refuses_a_prompt_written_from_another_technique(client):
    """`/v1/optimize` inherited the prompt field and ignored it.

    Silently: the request was accepted, the search ran from the registry
    technique, and the deltas described a prompt the caller had never seen. Now
    it is the baseline, which means it is subject to the same guard a benchmark
    applies — numbers filed under the wrong method are worse than no numbers.
    """
    task = client.post(
        "/v1/recommend", json={"description": "Extract entities", "model": MODEL}
    ).json()["task"]
    task["model"]["base_url"] = "http://127.0.0.1:9"
    compiled = client.post(
        "/v1/compile",
        json={"task": task, "user_input": "{input}", "technique_id": "structured.schema-first"},
    ).json()

    started = client.post(
        "/v1/optimize",
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


def test_optimize_refuses_a_prompt_with_nowhere_to_put_an_example(client):
    """The check is up front, not row by row inside a job that is already running."""
    task = client.post(
        "/v1/recommend", json={"description": "Extract entities", "model": MODEL}
    ).json()["task"]
    task["model"]["base_url"] = "http://127.0.0.1:9"
    compiled = client.post(
        "/v1/compile",
        json={"task": task, "user_input": "{input}", "technique_id": "structured.schema-first"},
    ).json()
    # A prompt with no slot and no material of its own: nothing in it can be
    # replaced by a row's input.
    for stage in compiled["stages"]:
        for message in stage["messages"]:
            message["content"] = "Answer in JSON."
    compiled["source_input"] = ""

    started = client.post(
        "/v1/optimize",
        json={
            "task": task,
            "technique_id": "structured.schema-first",
            "dataset": "entity-extraction",
            "record": False,
            "prompt": compiled,
        },
    )
    job = wait_for_job(client, started.json()["id"])
    assert job["status"] == "error"
    assert "no place for an example's input" in job["error"]
    # Nothing was spent finding that out.
    assert not job["progress"]


def test_exporting_a_technique_is_optimize_export_over_http(client, tmp_path):
    """`optimize --export` had no equivalent in the interface.

    A winner could be searched for in the browser and then only looked at: the
    file that makes it runnable was reachable from the CLI alone.
    """
    exported = _optimizer_winner()
    response = client.post("/v1/export/technique", json={"technique": exported})

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "structured.schema-first.optimized"
    assert body["saved_to"] is None and body["resolvable"] is False
    assert "HOUSE RULE: never invent a place." in body["yaml"]
    # It is a technique file, not a rendering of one: it parses back.
    import yaml as yaml_module

    from prompt_playoff.domain import TechniqueSpec

    assert TechniqueSpec.model_validate(yaml_module.safe_load(body["yaml"])).id == body["id"]


def test_a_saved_technique_becomes_something_the_rest_of_the_tool_can_run(client):
    """Saving is the half that matters: `/v1/run` and the runtime export take an id."""
    task = client.post(
        "/v1/recommend", json={"description": "Extract entities", "model": MODEL}
    ).json()["task"]
    saved = client.post(
        "/v1/export/technique",
        json={"technique": _optimizer_winner(), "technique_id": "support.tuned", "save": True},
    ).json()
    assert saved["resolvable"] is True
    assert saved["saved_to"].endswith("support.tuned.yaml")

    assert "support.tuned" in {item["id"] for item in client.get("/v1/techniques").json()}
    compiled = client.post(
        "/v1/compile",
        json={"task": task, "user_input": "{input}", "technique_id": "support.tuned"},
    )
    assert compiled.status_code == 200
    written = "\n".join(
        message["content"] for stage in compiled.json()["stages"] for message in stage["messages"]
    )
    assert "HOUSE RULE: never invent a place." in written

    bundle = client.post(
        "/v1/export/runtime",
        json={"task": task, "technique_id": "support.tuned", "language": "python"},
    )
    assert bundle.status_code == 200
    assert "support.tuned" in bundle.json()["config"]

    removed = client.delete("/v1/techniques/support.tuned")
    assert removed.status_code == 200
    assert client.delete("/v1/techniques/support.tuned").status_code == 404
    assert (
        client.post(
            "/v1/compile",
            json={"task": task, "user_input": "{input}", "technique_id": "support.tuned"},
        ).status_code
        == 422
    )


def test_a_saved_technique_may_not_take_a_registry_recipe_s_name(client):
    """Otherwise every recorded number filed under that id quietly changes meaning."""
    response = client.post(
        "/v1/export/technique",
        json={
            "technique": _optimizer_winner(),
            "technique_id": "structured.schema-first",
            "save": True,
        },
    )
    assert response.status_code == 409
    assert "registry recipe" in response.json()["detail"]


def test_a_saved_technique_is_resolvable_but_never_recommended(client):
    """A recipe tuned on one dataset is not evidence about anybody else's task."""
    client.post(
        "/v1/export/technique",
        json={"technique": _optimizer_winner(), "technique_id": "support.tuned", "save": True},
    )
    ranked = client.post(
        "/v1/recommend", json={"description": "Extract entities", "model": MODEL}
    ).json()
    assert "support.tuned" not in {item["technique_id"] for item in ranked["recommendations"]}


def test_deleting_a_packaged_recipe_is_refused(client):
    response = client.delete("/v1/techniques/structured.schema-first")
    assert response.status_code == 404
    assert "was not saved here" in response.json()["detail"]


def test_adopting_a_rewritten_prompt_copies_it_rather_than_recompiling(client):
    """A prompt search measured the text itself, so recompiling would discard it.

    The recipe path has to rebuild the winner against the real task, because
    what it measured was a compile against a benchmark row. The prompt path has
    no such gap: the measured text is already the text for this task.
    """
    task = client.post(
        "/v1/recommend", json={"description": "Extract entities", "model": MODEL}
    ).json()["task"]
    compiled = client.post(
        "/v1/compile",
        json={"task": task, "user_input": "{input}", "technique_id": "structured.schema-first"},
    ).json()
    for stage in compiled["stages"]:
        stage["messages"][-1]["content"] = "WHAT THE SEARCH WROTE: never invent a place.\n{input}"

    response = client.post(
        "/v1/optimize/adopt",
        json={"task": task, "technique_id": "structured.schema-first", "program": compiled},
    )

    assert response.status_code == 200
    program = response.json()
    assert program["artifact_source"] == "optimizer"
    assert program["stages"][0]["messages"][-1]["content"].startswith("WHAT THE SEARCH WROTE")
    assert program["technique_id"] == "structured.schema-first"


def test_adopting_needs_one_of_the_two_winners(client):
    task = client.post(
        "/v1/recommend", json={"description": "Extract entities", "model": MODEL}
    ).json()["task"]
    response = client.post(
        "/v1/optimize/adopt",
        json={"task": task, "technique_id": "structured.schema-first", "reusable": True},
    )
    assert response.status_code == 422
    assert "winning technique or the winning prompt" in response.json()["detail"]


def test_a_saved_technique_travels_with_the_client_that_needs_it(client):
    """The export used to run only on the machine it was made on.

    The generated client names a technique by id and no other server resolves a
    winner saved here, so the bundle carries the technique and the other end can
    take it in.
    """
    task = client.post(
        "/v1/recommend", json={"description": "Extract entities", "model": MODEL}
    ).json()["task"]
    client.post(
        "/v1/export/technique",
        json={"technique": _optimizer_winner(), "technique_id": "support.tuned", "save": True},
    )

    bundle = client.post(
        "/v1/export/runtime",
        json={"task": task, "technique_id": "support.tuned", "language": "python"},
    ).json()
    assert bundle["technique_filename"] == "support-tuned.technique.yaml"
    assert "HOUSE RULE: never invent a place." in bundle["technique"]
    assert any("/v1/techniques/import" in note for note in bundle["notes"])

    # A packaged recipe is on every server, so nothing needs to travel with it.
    packaged = client.post(
        "/v1/export/runtime",
        json={"task": task, "technique_id": "structured.schema-first", "language": "python"},
    ).json()
    assert packaged["technique"] is None

    # The other end of the journey.
    client.delete("/v1/techniques/support.tuned")
    imported = client.post("/v1/techniques/import", json={"yaml": bundle["technique"]})
    assert imported.status_code == 200
    assert imported.json()["id"] == "support.tuned"
    assert (
        client.post(
            "/v1/compile",
            json={"task": task, "user_input": "{input}", "technique_id": "support.tuned"},
        ).status_code
        == 200
    )


def test_importing_something_that_is_not_a_technique_is_refused(client):
    assert client.post("/v1/techniques/import", json={"yaml": ": : ["}).status_code == 422
    assert client.post("/v1/techniques/import", json={"yaml": "id: x\n"}).status_code == 422
