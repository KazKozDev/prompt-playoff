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
from prompt_playoff.graders import GradeContext, get_grader
from prompt_playoff.registry import Registry

CATALOGUE = Path(__file__).parents[1] / "src/prompt_playoff/data/business_cases.yaml"
BUSINESS = Path(__file__).parents[1] / "src/prompt_playoff/data/datasets/business"
STATIC = Path(__file__).parents[1] / "src/prompt_playoff/data/static"


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


def test_every_named_set_is_bundled_and_carries_its_reference(raw):
    for spec in raw["sets"]:
        assert spec["name"].startswith("business:"), spec["name"]
        for field in ("title", "shape", "source", "url", "license"):
            assert spec.get(field), f"{spec['name']} has no {field}"
        assert spec["url"].startswith("https://huggingface.co/datasets/")
        assert spec["source"] in spec["url"]
        path = BUSINESS / f"{spec['name'].split(':', 1)[1]}.jsonl"
        assert path.exists(), f"{spec['name']} is in the catalogue with no rows at {path}"


def test_bundled_rows_match_what_the_catalogue_promises(raw):
    """Rows are a sample, so the count is a floor — but the shape is not negotiable."""
    for spec in raw["sets"]:
        rows = load_jsonl(BUSINESS / f"{spec['name'].split(':', 1)[1]}.jsonl")
        assert len(rows) >= min(spec["rows"], 40), f"{spec['name']} has {len(rows)} rows"
        assert len({row.id for row in rows}) == len(rows)
        assert len({row.input for row in rows}) == len(rows)
        for row in rows:
            assert row.input.strip()
            assert row.expected not in (None, ""), f"{row.id} has no answer to be scored against"
            assert set(row.graders) == set(spec["graders"])
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
    named = {spec["name"] for spec in raw["sets"]}
    assert named <= set(registered)
    # And nothing extra: a file dropped into the directory without a catalogue
    # entry would be measurable with no source, licence or business case on it.
    assert {name for name in registered if name.startswith("business:")} == named


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
    assert payload["counts"]["available"] == payload["counts"]["sets"]
    for spec in payload["sets"]:
        assert spec["available"] and spec["examples"] > 0
    # The route is declared ahead of /v1/datasets/{name}, which would otherwise
    # answer 404 for a set called "catalog".
    assert "groups" in payload
