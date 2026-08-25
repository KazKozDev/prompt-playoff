"""The business catalogue holds together: mapping, rows, and what the API says.

The catalogue makes a claim the rest of the app cannot check for it — that a
score on business:support-reply is evidence about answering customers — so what
is tested here is the joins. A case citing a set nobody ships, a set whose file
was never fetched, a licence that quietly went missing: each of those turns the
screen into a brochure, and none of them raise on their own.
"""

import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from prompt_playoff.api import app
from prompt_playoff.business_catalog import CatalogError, catalog, group_of
from prompt_playoff.evals import load_jsonl
from prompt_playoff.graders import (
    REFERENCE_OVERLAP_GRADERS,
    GradeContext,
    get_grader,
)
from prompt_playoff.registry import Registry

CATALOGUE = Path(__file__).parents[1] / "src/prompt_playoff/data/business_cases.yaml"
BUSINESS = Path(__file__).parents[1] / "src/prompt_playoff/data/datasets/business"
STATIC = Path(__file__).parents[1] / "src/prompt_playoff/data/static"

EXPECTED_TAXONOMY = [
    (
        "Customer Support",
        [
            "Ticket classification",
            "Ticket routing",
            "Reply drafting",
            "Intent detection",
            "Conversation summary",
        ],
    ),
    (
        "Marketing",
        [
            "Ad copy generation",
            "Brand voice rewriting",
            "Review analysis",
            "Campaign brief generation",
            "SEO content generation",
        ],
    ),
    (
        "Sales & CRM",
        [
            "Lead qualification",
            "Outreach personalization",
            "Call insights extraction",
            "CRM note generation",
            "Objection detection",
        ],
    ),
    (
        "Operations",
        [
            "Document processing",
            "Workflow classification",
            "Data extraction",
            "Internal request routing",
            "Email prioritization",
        ],
    ),
    (
        "Finance & Accounting",
        [
            "Invoice extraction",
            "Expense classification",
            "Financial document QA",
            "Financial summary generation",
            "Budget variance explanation",
        ],
    ),
    (
        "Legal & Compliance",
        ["Contract review", "Clause extraction", "Compliance check", "PII detection", "Policy Q&A"],
    ),
    (
        "HR & Recruiting",
        [
            "Resume screening",
            "Job description generation",
            "Interview summary",
            "Candidate matching",
            "Employee Q&A",
        ],
    ),
    (
        "Product",
        [
            "Feedback classification",
            "Feature request clustering",
            "Research synthesis",
            "PRD / spec generation",
            "User story generation",
        ],
    ),
    (
        "Engineering & IT",
        ["Code generation", "Code explanation", "Bug triage", "Incident summary", "Technical Q&A"],
    ),
    (
        "Data & Analytics",
        [
            "Text-to-SQL",
            "Report generation",
            "Insight extraction",
            "Data explanation",
            "Metric commentary",
        ],
    ),
    (
        "Knowledge & Internal Search",
        [
            "Internal Q&A (RAG)",
            "Policy lookup",
            "Document search",
            "Knowledge base summarization",
            "Onboarding assistant",
        ],
    ),
    (
        "Localization",
        [
            "Translation",
            "Localization / adaptation",
            "Terminology consistency",
            "Multilingual content QA",
        ],
    ),
]


@pytest.fixture(scope="module")
def raw() -> dict:
    return yaml.safe_load(CATALOGUE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def cases(raw) -> list[dict]:
    return [case for group in raw["groups"] for case in group["cases"]]


def test_every_case_is_numbered_once_across_all_groups(cases):
    numbers = [case["number"] for case in cases]
    assert numbers == list(range(1, len(numbers) + 1))


def test_a_case_with_no_match_claims_no_dataset(cases):
    """The ten honest gaps stay gaps: `none` and a cited set contradict each other."""
    for case in cases:
        if case["match"] == "none":
            assert not case.get("sets"), f"case {case['number']} is 'none' but cites a set"
        else:
            evidence = case.get("sets") or case.get("references")
            assert evidence, f"case {case['number']} claims a {case['match']} match with nothing"


def test_every_case_carries_the_story_the_card_is_built_from(cases):
    for case in cases:
        assert case.get("story", "").strip(), f"case {case['number']} has no story"
        assert case["company"].strip()
        # A figure and what it is a figure of are one fact: half of it on a card
        # is a number with nothing under it.
        assert bool(case.get("claim")) == bool(case.get("claim_of")), case["number"]


def test_every_case_has_a_resolvable_audited_source(raw, cases):
    sources = {source["id"]: source for source in raw["case_sources"]}
    assert sources
    for source in sources.values():
        assert source["url"].startswith("https://")
        for field in ("title", "publisher", "source_type", "accessed_at"):
            assert source.get(field), f"source {source['id']} has no {field}"
        assert "published_at" in source, f"source {source['id']} guesses by omission"
    for case in cases:
        assert case["source_ref"] in sources, case["number"]
        assert case["evidence_status"] in {
            "verified_official",
            "qualified_official",
            "unverified",
        }
        assert case["evidence_note"].strip(), case["number"]


def test_case_source_and_evidence_status_reach_the_api_and_ui():
    result = catalog({})
    cases = [case for group in result["groups"] for case in group["cases"]]
    assert all(case["source_record"]["url"].startswith("https://") for case in cases)
    assert {case["evidence_status"] for case in cases} == {
        "verified_official",
        "qualified_official",
        "unverified",
    }
    javascript = (STATIC / "platform.js").read_text(encoding="utf-8")
    assert 'class="case-origin"' in javascript
    assert "Exact claim unverified" in javascript
    assert "Official source means" in javascript


def test_a_case_with_half_a_claim_is_refused(tmp_path, raw):
    broken = {
        **raw,
        "groups": [
            {
                "id": "email",
                "name": "Email",
                "headline": "Sort, classify & draft emails",
                "summary": "x",
                "art": "cat-email",
                "cases": [
                    {
                        "number": 1,
                        "task": "t",
                        "company": "c",
                        "story": "s",
                        "claim": "−30%",
                        "match": "none",
                    }
                ],
            }
        ],
    }
    (tmp_path / "business_cases.yaml").write_text(yaml.safe_dump(broken), encoding="utf-8")
    with pytest.raises(CatalogError, match="half a claim"):
        catalog({}, root=str(tmp_path))


def test_every_category_carries_what_its_tile_is_built_from(raw):
    """A tile is a picture, a headline and a caption, and none of it degrades well.

    A missing headline is a blank line in the largest type on the shelf, and an
    `art` naming a file that was never packaged is a broken-image icon on a
    screen whose whole job is to look pickable — neither raises on its own.
    """
    ids = [group["id"] for group in raw["groups"]]
    assert len(ids) == len(set(ids)), "two categories share an id, so one is unreachable"
    for group in raw["groups"]:
        for field in ("name", "headline", "summary", "art"):
            assert str(group.get(field, "")).strip(), f"group {group['id']} has no {field}"
        art = STATIC / f"{group['art']}.webp"
        assert art.exists(), f"group {group['id']} names tile art that is not packaged: {art}"


def test_every_named_set_has_license_provenance_and_only_cleared_sets_are_bundled(raw):
    for spec in raw["sets"]:
        assert spec["name"].startswith("business:"), spec["name"]
        for field in (
            "title",
            "shape",
            "source",
            "url",
            "license",
            "license_status",
            "license_url",
            "redistribution",
            "source_revision",
        ):
            assert spec.get(field), f"{spec['name']} has no {field}"
        assert spec["url"].startswith("https://huggingface.co/datasets/")
        assert spec["source"] in spec["url"]
        path = BUSINESS / f"{spec['name'].split(':', 1)[1]}.jsonl"
        assert path.exists() is spec["bundled"], spec["name"]
        if spec["bundled"]:
            assert spec["license_status"] == "verified_upstream"
        else:
            assert spec["redistribution"] == "source_only"


def test_bundled_rows_match_what_the_catalogue_promises(raw):
    """Rows are a sample, so the count is a floor — but the shape is not negotiable."""
    for spec in raw["sets"]:
        if not spec["bundled"]:
            continue
        rows = load_jsonl(BUSINESS / f"{spec['name'].split(':', 1)[1]}.jsonl")
        assert len(rows) >= min(spec["rows"], 40), f"{spec['name']} has {len(rows)} rows"
        assert len({row.id for row in rows}) == len(rows)
        assert len({row.input for row in rows}) == len(rows)
        for row in rows:
            assert row.input.strip()
            assert row.expected not in (None, ""), f"{row.id} has no answer to be scored against"
            declared = set(spec["graders"])
            assert declared <= set(row.graders)
            if not spec.get("contract"):
                assert set(row.graders) == declared
                continue
            # A set that names a contract carries, per row, the checks a rule
            # can decide — and every one of them is a check the human answer
            # already meets. Without that invariant the derivation would have
            # swapped a metric that marks good answers wrong for a rule that
            # does the same thing, which is not an improvement.
            assert {"forbidden_content", "length_limit"} & set(row.graders)
            context = GradeContext(
                output=str(row.expected), expected=row.expected, options=row.grader_options
            )
            for name in row.graders:
                if name in REFERENCE_OVERLAP_GRADERS:
                    continue
                score = get_grader(name)(context)
                assert score is None or score >= 1.0, (
                    f"{row.id}: the reference itself fails its own {name} check"
                )
            assert len(row.input) <= spec["max_input_chars"]


def test_each_set_is_graded_by_something_that_can_tell_right_from_wrong(raw):
    """The failure this catches is silent, which is why it is worth a test.

    A grader picked for the wrong column shape scores a correct answer 0 — exact
    match on a column of paraphrases, say — and the run reads as a failed prompt
    rather than as a mislabelled dataset. So every set is scored twice: once
    against its own gold answer, which has to come out full marks, and once
    against nonsense, which has to come out nothing.
    """
    for spec in raw["sets"]:
        if not spec["bundled"]:
            continue
        rows = load_jsonl(BUSINESS / f"{spec['name'].split(':', 1)[1]}.jsonl")[:12]
        gold, junk = [], []
        for row in rows:
            answer = row.expected if isinstance(row.expected, str) else json.dumps(row.expected)
            for name in row.graders:
                grade = get_grader(name)
                gold.append(grade(GradeContext(output=answer, expected=row.expected)))
                junk.append(grade(GradeContext(output="nonsense zzz", expected=row.expected)))
        scored = [value for value in gold if value is not None]
        missed = [value for value in junk if value is not None]
        assert scored, f"{spec['name']} is graded by nothing that returns a score"
        assert sum(scored) / len(scored) == 1.0, f"{spec['name']} does not score its own answer"
        assert sum(missed) / len(missed) < 0.2, f"{spec['name']} scores nonsense"


def test_every_bundled_set_is_registered_under_its_catalogue_name(raw):
    registered = Registry.load().datasets
    named = {spec["name"] for spec in raw["sets"] if spec["bundled"]}
    assert named <= set(registered)
    # And nothing extra: a file dropped into the directory without a catalogue
    # entry would be measurable with no source, licence or business case on it.
    assert {name for name in registered if name.startswith("business:")} == named


def test_business_taxonomy_has_every_reference_category_and_task_in_order():
    result = catalog({})
    assert [category["name"] for category in result["taxonomy"]] == [
        name for name, _ in EXPECTED_TAXONOMY
    ]
    assert [[task["name"] for task in category["tasks"]] for category in result["taxonomy"]] == [
        tasks for _, tasks in EXPECTED_TAXONOMY
    ]
    assert result["taxonomy_counts"] == {"categories": 12, "tasks": 59, "available": 0}


def test_taxonomy_mappings_only_name_registered_packaged_datasets(raw):
    registered = set(Registry.load().datasets)
    catalogued = {spec["name"] for spec in raw["sets"]}
    mapped = {
        task["dataset"]
        for category in raw["taxonomy"]
        for task in category["tasks"]
        if task.get("dataset")
    }
    assert mapped <= registered | catalogued


def test_taxonomy_availability_and_routes_follow_a_partial_server_catalogue():
    available = {"business:support-intent": 60, "translation": 120}
    result = catalog(available)
    tasks = {task["name"]: task for category in result["taxonomy"] for task in category["tasks"]}
    assert tasks["Ticket classification"] == {
        "id": "ticket-classification",
        "name": "Ticket classification",
        "mapped_dataset": "business:support-intent",
        "dataset": "business:support-intent",
        "available": True,
        "examples": 60,
        "route": "#dataset-library/business:support-intent",
    }
    # A task may route to a packaged benchmark rather than to a business set.
    assert tasks["Terminology consistency"]["mapped_dataset"] == "translation"
    assert tasks["Terminology consistency"]["available"] is True
    assert tasks["Terminology consistency"]["route"] == "#dataset-library/translation"
    assert tasks["Reply drafting"]["mapped_dataset"] == "business:support-reply"
    assert tasks["Reply drafting"]["dataset"] is None
    assert tasks["Reply drafting"]["route"] is None
    assert tasks["Text-to-SQL"]["mapped_dataset"] is None
    assert tasks["Text-to-SQL"]["available"] is False
    assert tasks["Text-to-SQL"]["route"] is None


def test_a_taxonomy_task_routing_to_an_unknown_dataset_is_refused(tmp_path, raw):
    """A mistyped route does not raise — it renders as a gap that reads deliberate.

    Every task is shown whether or not a set measures it, so `dataset: mbp` and
    `dataset:` absent look identical on the shelf: both say "No dataset". The
    only place the difference can still be seen is here.
    """
    broken = {
        **raw,
        "taxonomy": [
            {
                "id": "customer-support",
                "name": "Customer Support",
                "summary": "x",
                "tasks": [{"id": "t", "name": "T", "dataset": "business:no-such-set"}],
            }
        ],
    }
    (tmp_path / "business_cases.yaml").write_text(yaml.safe_dump(broken), encoding="utf-8")
    with pytest.raises(CatalogError, match="routes to unknown"):
        catalog({}, root=str(tmp_path))


def test_a_taxonomy_task_may_route_to_a_declared_packaged_benchmark(raw):
    """The five names outside `sets` are declared, not tolerated."""
    allowed = {spec["name"] for spec in raw["sets"]} | set(raw["benchmark_sets"])
    mapped = {
        task["dataset"]
        for category in raw["taxonomy"]
        for task in category["tasks"]
        if task.get("dataset")
    }
    assert mapped <= allowed
    # And the allowlist earns its keep: every name on it is really packaged.
    assert set(raw["benchmark_sets"]) <= set(Registry.load().datasets)


def test_every_packaged_business_set_is_reachable_from_the_library(raw):
    """A set nothing links to is installed, measurable, and findable by nobody.

    Not every set has a task whose shape it honestly matches, and forcing a
    route would be the worse lie. So the sources table below the shelf lists
    every packaged set, and it is filtered by the search alone — narrowing it to
    the sets the open categories route to is what hid these in the first place.
    """
    javascript = (STATIC / "platform.js").read_text(encoding="utf-8")
    assert "business.filter(visibleBusinessSet)" in javascript
    assert "function visibleBusinessSet(name)" in javascript
    # The taxonomy decides the shelf, never which packaged sets exist.
    assert "catalogueNames" not in javascript

    routed = {
        task["dataset"]
        for category in raw["taxonomy"]
        for task in category["tasks"]
        if task.get("dataset")
    }
    listed = {spec["name"] for spec in catalog({})["sets"]}
    assert {spec["name"] for spec in raw["sets"]} <= listed | routed


def test_a_category_takes_its_cases_from_the_sets_its_tasks_route_to(raw):
    """The file's two halves are joined by derivation, not by a hand-kept map.

    A category listing cases from a mapping written down separately drifts the
    first time a task is remapped, and drifts silently: the panel still fills.
    """
    javascript = (STATIC / "platform.js").read_text(encoding="utf-8")
    assert "function categoryCases(group)" in javascript
    assert "${cases.length ? renderCatalogCases(cases) : ''}" in javascript

    by_set: dict[str, list[int]] = {}
    for group in raw["groups"]:
        for case in group["cases"]:
            for name in case.get("sets", []):
                by_set.setdefault(name, []).append(case["number"])
    for category in raw["taxonomy"]:
        routed = {task["dataset"] for task in category["tasks"] if task.get("dataset")}
        drawn = {number for name in routed for number in by_set.get(name, [])}
        # A category routing to a business set has cases; one routing only to
        # task benchmarks honestly has none, and the panel omits the block.
        if routed & {spec["name"] for spec in raw["sets"]}:
            assert drawn, f"{category['id']} routes to business sets but draws no case"


def test_dataset_library_renders_links_and_unfocusable_disabled_task_rows():
    javascript = (STATIC / "platform.js").read_text(encoding="utf-8")
    styles = (STATIC / "styles.css").read_text(encoding="utf-8")
    assert 'class="cat-row cat-row-ready" href="${esc(task.route)}"' in javascript
    assert 'class="cat-row cat-row-off" aria-disabled="true"' in javascript
    assert (
        "tabindex"
        not in javascript[
            javascript.index("function renderCatalogZone()") : javascript.index(
                "function renderOpenGroup"
            )
        ]
    )
    assert ".cat-row-off" in styles
    assert ".cat-panel-task.off" in styles


def test_catalog_reports_only_the_sets_this_server_actually_has(raw):
    names = [spec["name"] for spec in raw["sets"]]
    partial = dict.fromkeys(names[:3], 60)
    result = catalog(partial)
    assert result["counts"]["sets"] == len(names)
    assert result["counts"]["available"] == 3
    assert [spec["available"] for spec in result["sets"]][:3] == [True, True, True]
    assert not any(spec["available"] for spec in result["sets"][3:])
    # A case is measurable only through a set that is really here.
    measurable = {
        case["number"]
        for group in result["groups"]
        for case in group["cases"]
        if case["measurable"]
    }
    assert measurable and all(
        any(name in partial for name in case["sets"])
        for group in result["groups"]
        for case in group["cases"]
        if case["number"] in measurable
    )


def test_group_counts_add_up_to_the_cases_in_the_group():
    result = catalog({})
    assert result["counts"]["cases"] == sum(len(g["cases"]) for g in result["groups"])
    for group in result["groups"]:
        counts = group["counts"]
        assert counts["direct"] + counts["partial"] + counts["none"] == counts["cases"]


def test_a_case_citing_a_set_nobody_ships_is_refused(tmp_path, raw):
    broken = {**raw}
    broken["groups"] = [
        {
            "id": "email",
            "name": "Email",
            "headline": "Sort, classify & draft emails",
            "summary": "x",
            "art": "cat-email",
            "cases": [
                {
                    "number": 1,
                    "task": "t",
                    "company": "c",
                    "match": "direct",
                    "story": "s",
                    "sets": ["business:nothing-like-this"],
                }
            ],
        }
    ]
    (tmp_path / "business_cases.yaml").write_text(yaml.safe_dump(broken), encoding="utf-8")
    with pytest.raises(CatalogError, match="unknown set"):
        catalog({}, root=str(tmp_path))


def test_group_of_names_the_work_a_set_stands_for():
    assert group_of("business:support-reply") == "Customer Support"
    assert group_of("agents") is None


def test_api_serves_the_catalogue_joined_to_the_bundled_rows():
    with TestClient(app) as client:
        payload = client.get("/v1/datasets/catalog").json()
    assert payload["counts"]["cases"] == 50
    assert payload["counts"]["available"] == sum(spec["bundled"] for spec in payload["sets"])
    for spec in payload["sets"]:
        assert spec["available"] is spec["bundled"]
        assert (spec["examples"] or 0) > 0 if spec["bundled"] else spec["examples"] is None
    # The route is declared ahead of /v1/datasets/{name}, which would otherwise
    # answer 404 for a set called "catalog".
    assert "groups" in payload
