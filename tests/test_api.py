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


def test_the_llm_or_not_guide_is_served_in_both_languages(client):
    assert "/llm-or-not/ru" in client.get("/llm-or-not").text
    assert "/llm-or-not" in client.get("/llm-or-not/ru").text
    assert 'lang="en"' in client.get("/llm-or-not").text
    assert 'lang="ru"' in client.get("/llm-or-not/ru").text


def test_the_guide_rail_offers_every_guide_the_server_serves(client):
    # A document served at a path nothing links to is a document nobody reads,
    # and a rail entry pointing at a path the server does not answer is a blank
    # frame. The two lists are written in different files, so they are compared
    # here rather than trusted.
    navigation = client.get("/assets/navigation.js").text
    rail = re.search(r"guides: \{.*?\n  \}", navigation, re.S)
    assert rail, "the guides mode rail was renamed"
    modes = set(re.findall(r"\['([a-z-]+)', '[^']+', '[^']+'\]", rail.group(0)))
    pages = re.search(r"function renderGuideMode.*?\n  \};", navigation, re.S)
    assert pages
    routes = dict(re.findall(r"'?([a-z-]+)'?:\['(/[a-z-]+)',", pages.group(0)))
    assert modes == set(routes), f"rail offers {modes}, renderGuideMode knows {set(routes)}"
    for path in routes.values():
        assert client.get(path).status_code == 200, f"the rail points at {path}, which 404s"


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
        "/llm-or-not",
        "/llm-or-not/ru",
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
    lifecycle = html.split('<nav class="lifecycle-nav"', 1)[1].split("</nav>", 1)[0]
    sidebar_destinations = re.findall(
        r'<a href="#[^"]+" data-global-tab="([^"]+)" data-screen="([^"]+)"'
        r'[^>]*data-testid="nav-[^"]+">',
        lifecycle,
    )

    assert set(sidebar_destinations) == {
        ("prompt", "prompt"),
        # The measurements taken on a prompt are screens in their own right and
        # are listed as such, not only reachable through the tab strip.
        ("report", "report"),
        ("comparison", "comparison"),
        ("optimization", "optimization"),
        ("dataset-library", "dataset-library"),
        # Upload and Hugging Face are sources for one outcome, so the rail has
        # one destination and the screen carries the source switch.
        ("dataset-add", "dataset-add"),
        ("results", "results"),
        ("judge", "judge"),
        ("test-lab", "test-lab"),
        # Production is two things: turning a measured prompt into files a
        # repository holds, and the decisions a model asked a person to make.
        # The regression gate is neither — it compares recorded runs, so it is
        # a mode of Results, where the runs are.
        ("ship", "ship"),
        ("reviews", "reviews"),
        ("techniques", "techniques"),
        ("guides", "guides"),
    }
    # Thirteen rows for thirteen destinations. A screen with modes gets one row,
    # pointing at its default mode; the mode rail on the screen carries the rest.
    # Results used to be listed twice, once on its history and once on the
    # regression gate, and it was the only screen in the rail that was.
    assert len(sidebar_destinations) == 13
    assert sidebar_destinations.count(("results", "results")) == 1
    assert 'data-testid="nav-settings"' in html
    assert 'data-testid="nav-logs"' in html
    assert 'data-testid="rail-model"' in html
    assert 'data-testid="model-chip"' in html
    assert 'data-testid="lifecycle-nav"' in html
    assert 'data-testid="drawer-toggle"' in html
    # One entry per approved lifecycle section, including the canonical Docs
    # destination rather than the old Reference section route.
    assert html.count('data-testid="bottom-') == 5
    assert 'data-testid="bottom-docs"' in html
    assert 'href="#guides/user"' in html
    assert ">Docs</a>" in html
    assert 'data-testid="bottom-reference"' not in html
    assert ">Guides<" in html
    # The sidebar used to repeat the prompt/dataset/model line that the context
    # bar already carries; one of the two had to go, and the header kept it.
    assert 'id="sidebar-prompt"' not in html
    assert 'id="context-prompt"' in html


def test_results_exposes_business_case_prompt_dataset_run_lineage(client):
    html = client.get("/").text
    selector = client.get("/assets/selector.js").text
    measurements = client.get("/assets/measurements.js").text
    navigation = client.get("/assets/navigation.js").text

    assert 'id="business-case-select"' in html
    assert 'id="business-case-name"' in html
    assert 'id="context-case"' in html
    assert "api('/v1/business-cases')" in selector
    assert "api('/v1/business-cases', {name, description:description.trim()})" in selector
    assert "business_case_id:state.businessCaseId || null" in selector
    for action in ("/v1/benchmark", "/v1/compare", "/v1/optimize"):
        request = measurements.split(f"api('{action}'", 1)[1].split("});", 1)[0]
        assert "businessCaseRequestFields()" in request
    assert "portfolioCases(records)" in navigation
    assert "historyPromptGroups(selectedCase.records)" in navigation
    assert "selectedPrompt.records.filter(item => item.dataset" in navigation
    assert "historyCaseKey(item)}:${historyPromptKey(item)}" in navigation
    assert "historyComparisonSeries(datasetRecords)" in navigation
    assert "const options = comparableRecords.map" in navigation
    assert "technique_id:state.historyTechnique" in navigation
    assert 'aria-label="Selected result lineage"' in navigation
    assert "Legacy and deliberately unassigned runs" in navigation


def test_add_dataset_unifies_sources_and_keeps_legacy_hash_aliases(client):
    html = client.get("/").text
    navigation = client.get("/assets/navigation.js").text

    assert html.count('data-testid="nav-dataset-add"') == 1
    assert 'data-testid="nav-dataset-upload"' not in html
    assert 'data-testid="nav-dataset-hub"' not in html
    assert "'dataset-upload':'dataset-add'" in navigation
    assert "'dataset-hub':'dataset-add'" in navigation
    assert "['upload', 'Upload file'" in navigation
    assert "['hugging-face', 'Hugging Face'" in navigation
    assert "['generate', 'Generate'" in navigation
    assert "renderDatasetUpload()" in navigation
    assert "renderDatasetHub()" in navigation
    assert "renderDatasetBuilder()" in navigation
    assert "focusMode:route.legacy" in navigation


def test_the_section_map_is_one_column_at_the_width_it_actually_gets(client):
    """A rule outlived the layout it was written for, and squeezed the words.

    The map used to run the full width of a section screen, so between 1100 and
    1480 it turned on its side: words in one column, drawing in the other. A
    later rule made it a fixed side column of about 340px at every width above
    1100 — and splitting 340px in two left the words in a column of zero, so
    every caption wrapped one word per line on all five section screens.
    """
    styles = client.get("/assets/styles.css").text

    assert 'grid-template-areas:"head plot"' not in styles
    assert "@media (min-width:1100px) and (max-width:1479px)" not in styles
    # It stays a flex column, which is what the narrow panel can actually hold.
    # The first `.section-map {` is a grid-column placement inside a media
    # query; the block that sets its own display is the one that matters.
    assert "\n    .section-map {\n      display:flex; flex-direction:column;" in styles


def test_ship_replaces_the_release_register_with_an_export(client):
    """The UI produces the file CI enforces; it does not re-implement the gate.

    `prompt-playoff check` reads committed thresholds and fails the build. The
    old Production section drove a hand-moved version register beside it — the
    same job, done worse, in a place no colleague or CI job can read.
    """
    navigation = client.get("/assets/navigation.js").text
    platform = client.get("/assets/platform.js").text

    assert "['releases', 'Releases'" in navigation
    assert "['spot-checks', 'Spot checks'" in navigation
    assert "ship:['Production', 'Ship'," in navigation
    # The register exports rather than only advancing labels.
    assert 'data-release-action="export"' in platform
    assert "downloadText(manifest.filename, manifest.content" in platform
    assert "downloadText(manifest.checks_filename, manifest.checks" in platform
    # And the merge left no screen behind under its old name.
    assert "release-center" not in platform
    assert "'release-center':'ship'" in navigation


def test_a_path_that_split_in_two_still_resolves_to_the_right_half(client):
    """`#release-center` became two screens, so its head no longer decides.

    Versions became Ship; the regression gate became a mode of Results, where
    the runs it compares live. Resolving on the first segment alone would open
    the register for a bookmarked gate — the right screen name, the wrong
    screen — so the whole path is looked up first.
    """
    navigation = client.get("/assets/navigation.js").text

    assert "const legacyPaths = {" in navigation
    assert "'release-center/versions':['ship', 'releases']" in navigation
    assert "'release-center/regressions':['results', 'regressions']" in navigation
    assert "const paired = legacyPaths[`${head}/${rest[0]}`];" in navigation


def test_the_merged_screens_left_no_second_implementation_behind(client):
    """Two ways to draw one screen is one way too many, and the dead one rots.

    Merging the source screens produced a mode rail in navigation.js and a
    two-source switch in datasets.js that did the same job. Only the rail is
    reachable, so the switch was a screen nobody could open, styled by CSS
    nobody could apply, wired to a `selectTab` option that does not exist.
    """
    datasets = client.get("/assets/datasets.js").text
    navigation = client.get("/assets/navigation.js").text
    styles = client.get("/assets/styles.css").text
    html = client.get("/").text

    for gone in ("renderDatasetAdd", "wireDatasetAdd", "applyDatasetSource", "datasetAddSource"):
        assert gone not in datasets, f"{gone} is a second Add-dataset screen"
    assert "dataset-source" not in styles
    # One name for one thing: a link asks for a mode, never for a "source".
    for text in (datasets, navigation, html, client.get("/assets/platform.js").text):
        assert "data-dataset-source" not in text
    assert "datasetSource" not in navigation

    # The guides are reached through their own screen, so the three per-document
    # panels that used to render them are unreachable.
    assert "docPages" not in navigation
    assert "renderGuideMode" in navigation


def test_system_screens_keep_the_rail_open_and_claim_no_mobile_destination(client):
    """Models & keys and Jobs & logs are under none of the five sections.

    Read off the rail alone they came back sectionless, and a blank section is
    the same instruction as "close every section" — so arriving at Models & keys
    collapsed the whole rail on the way in.
    """
    navigation = client.get("/assets/navigation.js").text
    html = client.get("/").text

    assert '.sidebar-system a[data-screen="${screen}"]' in navigation
    assert "? 'system' : ''" in navigation
    guard = 'if (!document.querySelector(`.sidebar-group[data-section="${section}"]`))'
    assert f"{guard} return;" in navigation
    # No bucket claims them: aria-current on a destination you are not at is a
    # worse answer than none.
    destinations = navigation.split("const sectionDestinations = {", 1)[1].split("}", 1)[0]
    assert "system" not in destinations
    # And the crumb path skips a section that has no screen to land on.
    assert "if (sectionTabs.includes(`s-${section}`)) trail.push(" in navigation
    assert 'data-testid="nav-settings"' in html.split('class="sidebar-system"', 1)[1]


def test_navigation_consolidates_destinations_and_keeps_every_old_hash(client):
    navigation = client.get("/assets/navigation.js").text
    html = client.get("/").text

    for route, parent in {
        "dataset-builder": "dataset-add",
        "dataset-bundled": "dataset-library",
        "history": "results",
        "analysis": "results",
        "model-matrix": "test-lab",
        "context-lab": "test-lab",
        "regressions": "results",
        "releases": "ship",
        "release-center": "ship",
        "production": "ship",
        "help": "guides",
        "evaluation": "guides",
        "prompt-vs-finetuning": "guides",
        "llm-or-not": "guides",
    }.items():
        pattern = rf"(?:'{re.escape(route)}'|{re.escape(route)}):'{re.escape(parent)}'"
        assert re.search(pattern, navigation)
    for canonical in (
        "#results/history",
        "#test-lab/models",
        "#ship/releases",
        "#guides/user",
    ):
        assert canonical in html
    # `#results/regressions` is a canonical route without a row in the shell:
    # the rail links a screen's default mode, and the mode rail on Results syncs
    # the URL to the other two.
    assert "#results/regressions" not in html
    assert "['regressions', 'Regression gate'," in navigation
    assert 'role="tablist"' in navigation
    assert "event.key === 'Home'" in navigation
    assert "event.key === 'End'" in navigation
    assert "syncUrl:route.legacy" in navigation
    assert "replace:route.legacy" in navigation


def test_navigation_uses_clear_labels_and_production_lifecycle_order(client):
    html = client.get("/").text
    navigation = client.get("/assets/navigation.js").text

    assert '<span class="section-name">Prompt Studio</span>' in html
    assert '<span class="section-name">Evaluation</span>' in html
    assert 'data-testid="nav-comparison">Technique comparison</a>' in html
    assert 'data-testid="nav-judge">Answer judging</a>' in html
    assert 'data-testid="bottom-prompt">Prompt Studio</a>' in html
    assert 'data-testid="bottom-evaluate">Evaluate</a>' in html
    assert "comparison:['Prompt Studio', 'Technique comparison']" in navigation
    assert "judge:['Evaluation', 'Answer judging'," in navigation

    production = html.split('id="section-ship"', 1)[1].split("</div>", 1)[0]
    assert re.findall(r'data-testid="nav-[^"]+">([^<]+)</a>', production) == ["Ship", "Reviews"]
    assert (
        'href="#ship/releases" data-global-tab="ship" '
        'data-screen="ship" data-mode="releases" data-testid="nav-ship"' in production
    )

    # The regression gate compares two recorded runs, so it lives where the runs
    # are rather than under the register of versions — as a mode of Results,
    # reached from the mode rail there and not from a second row of its own.
    evaluation = html.split('id="section-check"', 1)[1].split("</div>", 1)[0]
    assert re.findall(r'data-testid="nav-[^"]+">([^<]+)</a>', evaluation) == [
        "Results",
        "Answer judging",
        "Test lab",
    ]
    assert "nav-regressions" not in html
    assert "['regressions', 'Regression gate'," in navigation


@pytest.mark.parametrize("path", ["/assets/missing.js", "/assets/.hidden.js", "/assets/index.html"])
def test_static_asset_route_rejects_unknown_or_unsupported_files(client, path):
    assert client.get(path).status_code == 404


@pytest.mark.parametrize("section", ["prompt", "examples", "check", "ship", "reference"])
def test_no_section_drawing_is_fetched_for_a_screen_that_cannot_show_one(client, section):
    """The drawings went when the flat visual language arrived.

    Both call sites — the home tile and the section spotlight — had been painted
    out in CSS, so five images were fetched on every visit to Home and never
    drawn once. This is the old packaging test turned around: the guarantee now
    is that nothing asks for them.
    """
    javascript = client.get("/assets/navigation.js").text
    styles = client.get("/assets/styles.css").text

    assert f"section-{section}.webp" not in javascript
    assert "sectionArt" not in javascript
    assert "spotlight" not in javascript
    assert "spotlight" not in styles


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


def test_a_set_of_prose_answers_reports_what_word_overlap_scores_by_chance(client):
    """Said on the shelf, before a model is ever called.

    Four templated replies about four different things share nearly every word.
    A set like that cannot be scored by word overlap at all, and the cheapest
    place to learn it is the moment the rows arrive — not after an evening spent
    improving a prompt against a number with no room to move.
    """
    rows = [
        {
            "id": f"reply-{index}",
            "input": f"Ticket {index}",
            "expected": (
                f"Thank you for contacting us about your {word}. "
                "We are looking into it now and will be in touch shortly."
            ),
        }
        for index, word in enumerate(["order", "invoice", "refund", "delivery"])
    ]
    body = client.post(
        "/v1/datasets/upload",
        files={
            "file": (
                "replies.jsonl",
                "\n".join(json.dumps(row) for row in rows) + "\n",
                "application/x-ndjson",
            )
        },
    ).json()
    assert body["free_text"] == 4
    assert body["token_f1_chance_level"] > 0.8

    listed = next(
        item for item in client.get("/v1/datasets").json() if item["name"] == body["name"]
    )
    assert listed["token_f1_chance_level"] == body["token_f1_chance_level"]

    # A set whose rows name graders of their own is not scored this way, so it
    # claims no floor rather than quoting one nobody will read.
    entities = next(
        item for item in client.get("/v1/datasets").json() if item["name"] == "entity-extraction"
    )
    assert entities["free_text"] == 0
    assert entities["token_f1_chance_level"] is None


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
    assert "word overlap" in body["grader_help"]["token_f1"]
    assert set(body["grader_help"]) == set(body["graders"])


def test_capabilities_serves_the_warning_that_goes_beside_a_word_overlap_score(client):
    """A number nobody warned about is the one that sends a reader to fix a
    prompt that was never broken. The warning travels with the number."""
    body = client.get("/v1/capabilities").json()
    assert "token_f1" in body["reference_overlap_graders"]
    assert "not whether the answer is right" in body["grader_caveats"]["token_f1"]
    assert set(body["grader_caveats"]) <= set(body["graders"])
    # A share of answers and an average score are different claims, and only the
    # first may be printed as "N in 100 were correct".
    assert "exact_match" in body["pass_rate_graders"]
    assert "token_f1" not in body["pass_rate_graders"]
    assert set(body["pass_rate_graders"]) <= set(body["graders"])


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
    business_case = client.post(
        "/v1/business-cases",
        json={"name": "Entity extraction", "description": "Extract entities"},
    ).json()
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
            "business_case_id": business_case["id"],
        },
    )
    job = wait_for_job(client, started.json()["id"])
    assert job["status"] == "done"

    experiment_id = job["result"]["experiment_id"]
    assert experiment_id
    experiment = client.get(f"/v1/experiments/{experiment_id}")
    assert experiment.status_code == 200
    assert experiment.json()["business_case_id"] == business_case["id"]
    assert experiment.json()["prompt_version"] == 1


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


def test_the_empty_method_panel_does_not_offer_a_method_to_switch_to(client):
    """A screen with nothing on it must not describe the screen with something.

    The lead read "One is in use; you can switch to another at any time" and
    printed directly above "No method satisfies the constraints you set", which
    invited the user to switch between nothing and nothing. The empty state has
    its own lead, and it names where the constraints are set: they come from the
    task and from Settings, and neither is on this panel.
    """
    selector = client.get("/assets/selector.js").text

    assert "const RESULTS_LEAD_EMPTY =" in selector
    assert "resultsHead(RESULTS_LEAD_EMPTY)" in selector
    # The head takes the lead as an argument, so there is one heading, not two
    # copies of one drifting apart.
    assert "function resultsHead(lead = RESULTS_LEAD)" in selector
    assert selector.count("<h2>Method</h2>") == 1
    assert "Change one of them and create the prompt again." in selector


def test_the_library_can_pick_the_set_it_says_it_picks(client):
    """The screen's lead promises the choice; one field has to receive it.

    The library said "this is where you pick what a score will be computed
    against" while the only control that wrote ``state.run.dataset`` was the
    ``Measure against`` select on the three run screens. Two doors onto one
    field are fine; a door that opens onto nothing is what this guards.
    """
    platform = client.get("/assets/platform.js").text
    measurements = client.get("/assets/measurements.js").text

    assert "function measureAgainstBand(name)" in platform
    assert "measureAgainstBand(only)" in platform
    assert "${measureCell(name)}${deleteCell(name)}" in platform
    # The same field the run screens write, so the two can never disagree.
    assert "state.run.dataset = name;" in platform
    assert "field.dataset.runField] = field.value" in measurements


def test_the_set_field_is_grouped_by_where_the_rows_came_from(client):
    """A flat alphabetical list opened on the class the screen warns about."""
    measurements = client.get("/assets/measurements.js").text

    groups = measurements.split("const DATASET_GROUPS = [", 1)[1].split("];", 1)[0]
    assert groups.index("Your sets") < groups.index("Ready-made datasets by business task")
    business = groups.index("Ready-made datasets by business task")
    assert business < groups.index("Shipped with the tool")
    assert "<optgroup label=" in measurements


def test_results_opens_on_a_case_that_has_runs(client):
    """One empty business case was enough to open the screen on nothing.

    The body said "No runs yet" under a summary counting every run on the
    server, all of them one row below under Unassigned.
    """
    navigation = client.get("/assets/navigation.js").text

    opener = "if (!state.historyCaseId || !validCaseIds.has(state.historyCaseId)) {"
    default = navigation.split(opener, 1)[1].split("}", 1)[0]
    named_with_runs = default.index("item.id !== UNASSIGNED_CASE_ID && item.records.length")
    any_with_runs = default.index("cases.find(item => item.records.length)")
    named_empty = default.index("cases.find(item => item.id !== UNASSIGNED_CASE_ID)?.id")
    assert named_with_runs < any_with_runs < named_empty


def test_reviews_does_not_promise_the_releases_it_refuses(client):
    """The lead listed registered releases; the screen's own panel denies them."""
    navigation = client.get("/assets/navigation.js").text

    lead = navigation.split("reviews:['Production', 'Reviews', '", 1)[1].split("']", 1)[0]
    assert "registered releases" not in lead
    assert "Registering a release does not land here." in lead
    assert "Releases do not land here" in client.get("/assets/platform.js").text


def test_smart_run_consumes_nothing_the_reader_has_not_seen(client):
    """Its one input used to arrive already filled in, on a hidden screen.

    The task field carried the same sentence as both its placeholder and its
    value, and Smart run — pressed from Home, where the composer is hidden —
    checked only the dataset. So the default outcome of the app's headline
    button was a full measure-and-optimize cycle over the example text.
    """
    html = client.get("/").text
    navigation = client.get("/assets/navigation.js").text

    field = html.split('<textarea id="description"', 1)[1].split("</textarea>", 1)[0]
    assert "placeholder=" in field
    assert field.rstrip().endswith(">"), "the field must open empty"

    smart = navigation.split("function wireSmartStart(", 1)[1].split("\nconst routeAliases", 1)[0]
    # The task is asked for before the examples, because there is nothing to
    # measure a set against until it exists.
    task_check = smart.index("Describe the task first")
    dataset_check = smart.index("Choose a set of examples first")
    assert task_check < dataset_check
    # The task still only exists on the composer, so its refusal still leaves
    # for it. The set is now a field on the card the button lives on, so its
    # refusal points at that field instead of leaving for a different screen.
    assert "selectTab('prompt', {focus:true});" in smart
    assert "querySelector('[data-run-field=\"dataset\"]')?.focus();" in smart
    # And Home says what the button is holding before it is pressed.
    assert "function smartRunHolds()" in navigation


def test_a_smart_run_refusal_expires_with_the_field_it_named(client):
    """The rail card kept its refusal for the rest of the session.

    Both of Smart run's refusals were written into the one line that reports
    the button's state and left there — "Describe the task first" stayed under
    the button past the task being typed, past the prompt being compiled, past
    the measurement. So each refusal now records the field it is waiting for,
    and the line retires itself once that field arrives.
    """
    navigation = client.get("/assets/navigation.js").text
    measurements = client.get("/assets/measurements.js").text

    smart = navigation.split("function wireSmartStart(", 1)[1].split("\nconst routeAliases", 1)[0]
    # Neither refusal is printed without naming what would satisfy it.
    assert "'Describe the task first" in smart and "'task');" in smart
    assert "'Choose a set of examples first" in smart and "'dataset');" in smart
    assert "node.dataset.waitingFor = waitingFor" in smart

    # And the line is cleared by both of the things that can satisfy it: typing
    # the task, and any redraw that follows a dataset being chosen.
    assert "function clearSmartRefusal()" in navigation
    assert "if (event.target.id !== 'description') return;" in navigation
    assert "clearSmartRefusal();" in navigation
    assert "clearSmartRefusal();" in measurements.split("function refreshActions(", 1)[1]


def test_the_next_step_is_stated_before_the_prompt_and_not_under_it(client):
    """At the foot of a compiled prompt, the next step is off the screen.

    The block naming the one step not yet taken sat after the messages, the
    footer and the notes: on the rendered page it landed at 919px of a 2418px
    column, below the fold and behind a wall of monospace. The only pointer out
    of the screen was in its least-read place, so it stands above the prompt
    now, beside the copy buttons.
    """
    measurements = client.get("/assets/measurements.js").text

    program = measurements.split("function renderProgram(", 1)[1].split("\nfunction ", 1)[0]
    assert program.count("${nextStep()}") == 1
    assert program.index("${nextStep()}") < program.index("${stages}")


def test_the_opening_run_is_one_the_scorecard_will_stand_behind(client):
    """At one run per example the verdict disowns its own number."""
    core = client.get("/assets/core.js").text
    measurements = client.get("/assets/measurements.js").text

    assert "repeats:3" in core.split("run:{", 1)[1].split("}", 1)[0]
    # The caution that made the old default wrong is still there to be earned.
    assert "One run per example" in measurements


def test_ship_does_not_offer_a_form_it_will_refuse(client):
    """The register form stood under its own "author a prompt first" band."""
    platform = client.get("/assets/platform.js").text

    releases = platform.split("function renderReleases()", 1)[1].split("\nfunction ", 1)[0]
    assert '${state.program ? `<section class="screen-body">' in releases
    assert "Author a prompt before registering a release." in releases
    # Reading the register needs no prompt, so that half is not behind the gate.
    assert releases.index("<h2>The register</h2>") > releases.index("${state.program ?")


def test_the_narrow_window_keeps_what_every_number_depends_on(client):
    """Hiding the artifacts bar took the model picker with it."""
    styles = client.get("/assets/styles.css").text

    assert ".context-artifacts { display:none; }" not in styles
    assert ".context-case { display:none !important; }" not in styles
    assert ".context-artifacts { order:1; flex:1 0 100%;" in styles


def test_a_structured_right_answer_is_shown_as_json_not_as_object_object(client):
    """`String({})` is "[object Object]", which is the one thing a row cannot say.

    Both surfaces that print a dataset row — the library's preview table and the
    measurement report's example cards — used to stringify the expected answer
    directly, so every extraction set showed "[object Object]" in the column
    headed "Right answer". The fix is one shared helper, not two: a second copy
    is how these two screens would drift apart again.
    """
    core = client.get("/assets/core.js").text
    platform = client.get("/assets/platform.js").text
    measurements = client.get("/assets/measurements.js").text

    assert "const asText = value =>" in core
    assert "JSON.stringify(value, null, 2)" in core

    assert "const cell = value => esc(asText(value).slice(0, 240));" in platform
    assert "const cut = (value, limit) => esc(asText(value).slice(0, limit));" in measurements

    # No second implementation, and nothing left rendering a row through String().
    assert "JSON.stringify(value, null, 2)" not in platform
    assert "JSON.stringify(value, null, 2)" not in measurements
    for source in (platform, measurements):
        assert "String(value ?? '')" not in source


def test_the_report_takes_its_warning_from_the_server_rather_than_keeping_a_copy(client):
    """One wording for a grader, in the module that applies it.

    A caveat written into the page would be a second definition of what a
    grader means, free to drift from the code the moment either changes — the
    same reason `grader_help` is served rather than copied. So the page has to
    look these up, and it has to actually use them: on the report, and on the
    panel that names the headline grader *before* a run is spent.
    """
    catalog = client.get("/assets/catalog.js").text
    measurements = client.get("/assets/measurements.js").text
    platform = client.get("/assets/platform.js").text
    datasets = client.get("/assets/datasets.js").text

    assert "capabilities.grader_caveats" in catalog
    assert "capabilities.pass_rate_graders" in catalog
    # No page may hold its own copy of the sentence.
    body = measurements + platform + datasets
    assert "not whether the answer is right" not in body

    # Beside the score, and before the run that produces it.
    assert "graderCaveat(c.quality_grader)" in measurements
    assert "graderCaveat(headline)" in measurements
    # A partial-credit mean is never read out as a share of answers.
    assert "isPassRate(c.quality_grader)" in measurements
    assert "out of every 100 answers</strong> passed" in measurements
    # The measured floor, wherever a set is chosen or a score is read.
    assert "quality_chance_level" in measurements
    assert "token_f1_chance_level" in platform
    assert "token_f1_chance_level" in datasets


def test_a_rubric_verdict_covers_a_whole_run_and_stays_a_model_opinion(client, monkeypatch):
    """The judge used to answer one question nobody had.

    Whether one answer beats another settles an argument about one example. The
    question a person has about a drafting prompt is whether it writes well
    across the set, and that is what this returns — a win rate against the
    reference answers, blind, with one review item for the batch and no route
    into a benchmark number or a CI gate.
    """
    from prompt_playoff.domain import ModelResult

    async def generate(prompt, model, timeout_seconds=120):
        body = prompt.messages[1].content
        first = body.split("FIRST ANSWER:\n", 1)[1].split("\n\nSECOND ANSWER:", 1)[0]
        winner = "first" if first.startswith("model wrote") else "second"
        return ModelResult(content=json.dumps({"winner": winner, "rationale": "clearer"}), usage={})

    service = client.app.state.service
    monkeypatch.setattr(
        service, "provider", lambda *a, **k: type("P", (), {"generate": staticmethod(generate)})()
    )
    rows = client.get("/v1/datasets/summarization").json()[:4]
    body = client.post(
        "/v1/evaluate/rubric",
        json={
            "dataset": "summarization",
            "rubric": ["keeps every named entity", "reads as one sentence"],
            "judge_model": {"provider": "ollama", "model_id": "judge-7b"},
            "runs": [
                {
                    "example_id": row["id"],
                    "repeat": 0,
                    "output": f"model wrote this for {row['id']}",
                    "grades": {},
                    "latency_seconds": 0.1,
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "calls": 1,
                }
                for row in rows
            ],
        },
    ).json()

    assert body["wins"] == len(rows)
    assert body["win_rate"] == 1.0
    assert body["status"] == "pending_human_review"
    assert body["review_id"]
    assert "preferred these answers to the reference" in body["summary"]
    # One item for the batch, not one per row: a person confirming a verdict is
    # confirming the verdict, not clicking through fifty of them.
    judged = [item for item in client.get("/v1/reviews").json() if item["kind"] == "judge"]
    assert len(judged) == 1


def test_a_run_with_no_written_reference_is_refused_rather_than_judged_against_nothing(client):
    body = client.post(
        "/v1/evaluate/rubric",
        json={
            "dataset": "entity-extraction",
            "rubric": ["clarity"],
            "judge_model": {"provider": "ollama", "model_id": "judge-7b"},
            "runs": [
                {
                    "example_id": "entity-extraction-001",
                    "repeat": 0,
                    "output": "anything",
                    "grades": {},
                    "latency_seconds": 0.1,
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "calls": 1,
                }
            ],
        },
    )
    assert body.status_code == 422
    assert "graded by rule, not judged" in body.json()["detail"]


def test_the_report_says_which_graders_nobody_chose(client):
    measurements = client.get("/assets/measurements.js").text
    assert "report.inferred_graders" in measurements
    assert "not by you" in measurements


def test_a_search_with_no_number_worth_maximising_is_refused_at_the_click(client):
    """Refused as an answer to the click, not as a failed run.

    A job that dies halfway reads as something broken. This is not broken — it
    is the tool declining to spend an evening raising a number that cannot
    decide anything — so it comes back immediately, with a code the screen can
    act on and an override that relabels what the result means.
    """
    rows = [
        {
            "id": f"r{index}",
            "input": f"ticket {index}",
            "expected": (
                f"Thank you for contacting us about your {word}. "
                "We are looking into it now and will be in touch shortly."
            ),
        }
        for index, word in enumerate(["order", "invoice", "refund", "delivery", "return"])
    ]
    body = {
        "task": {"task_type": "summarization", "model": {"provider": "ollama", "model_id": "x"}},
        "technique_id": "direct.explicit-constraints",
        "examples": rows,
        "record": False,
    }
    refused = client.post("/v1/optimize", json=body)
    assert refused.status_code == 422
    detail = refused.json()["detail"]
    assert detail["code"] == "unmeasurable_objective"
    assert detail["chance_level"] > 0.35
    assert "contains_all" in detail["message"]

    # Saying so explicitly is allowed; being surprised by it is what is not.
    allowed = client.post("/v1/optimize", json={**body, "allow_noisy_objective": True})
    assert allowed.status_code == 200


def test_the_screen_can_act_on_the_refusal_and_offer_to_override_it(client):
    measurements = client.get("/assets/measurements.js").text
    core = client.get("/assets/core.js").text
    # The code, not the wording: a screen that matched on the sentence would
    # break the moment the sentence improved.
    assert "error.code" in core
    assert "'unmeasurable_objective'" in measurements
    assert 'data-action="optimize-anyway"' in measurements
    assert "allow_noisy_objective" in measurements


def test_the_judge_screen_judges_a_run_and_not_only_a_pair(client):
    platform = client.get("/assets/platform.js").text
    assert "'/v1/evaluate/rubric'" in platform
    assert "Judge a whole run" in platform
    # And says what the number is not, where the number is shown.
    assert "no route into a scorecard" in platform


def test_the_dataset_shelf_can_read_requirements_off_prose_rows(client):
    platform = client.get("/assets/platform.js").text
    assert "derive-requirements" in platform
    assert "/requirements" in platform


def test_a_set_of_prose_rows_can_be_given_requirements_without_leaving_the_screen(client):
    """The half of the fix that only existed in the terminal.

    Somebody brings their own drafting rows through the browser; deriving the
    requirements that make them gateable used to mean finding a CLI command.
    """
    rows = [
        {
            "id": f"r{index}",
            "input": f"Ticket about my {word} A-{4400 + index}",
            "expected": (
                f"About A-{4400 + index}: thank you for contacting us about your {word}. "
                "We are looking into it now and will be in touch shortly."
            ),
        }
        for index, word in enumerate(["order", "invoice", "refund", "delivery", "return"])
    ]
    name = client.post(
        "/v1/datasets/upload",
        files={
            "file": (
                "tickets.jsonl",
                "\n".join(json.dumps(row) for row in rows) + "\n",
                "application/x-ndjson",
            )
        },
    ).json()["name"]

    body = client.post(f"/v1/datasets/{name}/requirements", json={"contract": "reply"}).json()
    assert body["requirements"]["contains_all"] == len(rows)
    assert body["requirements"]["forbidden_content"] == len(rows)
    # A checkable requirement now answers for quality, so no row is left with
    # word overlap standing in for it.
    assert body["still_overlap_scored"] == 0

    # Pressing it twice is a reasonable thing to do, and must not report a set
    # that is fully derived as one nothing could be derived from.
    again = client.post(f"/v1/datasets/{name}/requirements", json={"contract": "reply"}).json()
    assert again["requirements"] == body["requirements"]
    assert again["added"] == {}

    # A bundled set already carries whatever contract its catalogue declares.
    refused = client.post(
        "/v1/datasets/business:support-reply/requirements", json={"contract": "reply"}
    )
    assert refused.status_code == 409


def test_rows_with_no_requirement_to_find_are_told_so_rather_than_left_looking_fixed(client):
    """Half the honesty of this feature is admitting when it found nothing."""
    rows = [
        {
            "id": f"r{index}",
            "input": f"ticket {index}",
            "expected": (
                f"Thank you for contacting us about your {word}. "
                "We are looking into it now and will be in touch shortly."
            ),
        }
        for index, word in enumerate(["order", "invoice", "refund", "delivery", "return"])
    ]
    name = client.post(
        "/v1/datasets/upload",
        files={
            "file": (
                "plain.jsonl",
                "\n".join(json.dumps(row) for row in rows) + "\n",
                "application/x-ndjson",
            )
        },
    ).json()["name"]
    body = client.post(f"/v1/datasets/{name}/requirements", json={"contract": "reply"}).json()
    assert "contains_all" not in body["requirements"]
    assert body["still_overlap_scored"] == len(rows)
