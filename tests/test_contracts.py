"""Requirements derived from rows that carry only a reference answer.

The rule this file exists to hold: a derived requirement is one the human
answer already meets. Without it the module would trade a metric that marks
good answers wrong for a rule that does the same thing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from prompt_playoff.contracts import (
    apply_requirements,
    channel_limit,
    requirements_for,
)
from prompt_playoff.evals import load_jsonl
from prompt_playoff.graders import (
    REFERENCE_OVERLAP_GRADERS,
    GradeContext,
    get_grader,
    headline_grader,
)

ROOT = Path(__file__).parents[1]
BUSINESS = ROOT / "src/prompt_playoff/data/datasets/business"
CATALOGUE = ROOT / "src/prompt_playoff/data/business_cases.yaml"


def test_a_reply_has_to_carry_the_identifier_back():
    graders, options = requirements_for(
        "Hi, where is order A-4471? It was due Tuesday.",
        "Thanks for checking — A-4471 left the warehouse and arrives Thursday.",
        kind="reply",
        max_chars=800,
    )
    assert options["contains"] == ["A-4471"]
    assert "forbidden_content" in graders and "length_limit" in graders


def test_an_identifier_only_the_question_mentions_is_not_required():
    """The person did not repeat it, so requiring it would score the model
    against a reply nobody wrote."""
    _, options = requirements_for(
        "Where is order A-4471?",
        "It shipped on Monday and should arrive this week.",
        kind="reply",
        max_chars=800,
    )
    assert "contains" not in options


def test_a_placeholder_the_question_itself_uses_is_required_not_forbidden():
    """What `business:support-reply` turned out to be.

    Every question in that corpus asks about order `{{Order Number}}` and every
    answer says it back. Forbidding the token would fail all sixty references;
    requiring it is the same contract every other reply set has — carry the
    order reference back — in the vocabulary those rows use.
    """
    graders, options = requirements_for(
        "question about cancelling order {{Order Number}}",
        "I've understood you have a question regarding canceling order {{Order Number}}.",
        kind="reply",
        max_chars=800,
    )
    assert options["contains"] == ["{{Order Number}}"]
    assert all("{{" not in pattern for pattern in options.get("forbidden_patterns", []))


def test_an_unfinished_draft_is_forbidden_where_the_question_did_not_ask_for_it():
    graders, options = requirements_for(
        "Draft a welcome note for a new customer.",
        "Welcome aboard — we are glad you are here.",
        kind="draft",
        max_chars=800,
    )
    assert "forbidden_content" in graders
    grade = get_grader("forbidden_content")
    assert grade(GradeContext(output="Dear [INSERT NAME], welcome.", options=options)) == 0.0
    assert grade(GradeContext(output="Welcome aboard, Priya.", options=options)) == 1.0


def test_a_summary_has_to_keep_the_facts_the_human_summary_kept():
    _, options = requirements_for(
        "The council approved 14 March. Costs fell 18%. Long Beach Boulevard reopens.",
        "On 14 March the council approved the plan; costs fell 18% and Long Beach "
        "Boulevard reopens.",
        kind="summary",
        max_chars=800,
    )
    assert "18%" in options["contains"]
    assert "Long Beach Boulevard" in options["contains"]


def test_nothing_is_required_that_the_reference_itself_would_fail():
    """The invariant, stated directly.

    Here the reference is longer than the limit it would be given, so the limit
    is dropped rather than applied to a row that cannot meet it.
    """
    graders, options = requirements_for(
        "Explain the policy.",
        "x" * 500,
        kind="draft",
        max_chars=100,
    )
    assert "length_limit" not in graders
    assert "max_chars" not in options


def test_the_channel_limit_is_read_off_what_people_wrote_and_is_generous():
    limit = channel_limit(["a" * 100, "b" * 200, "c" * 150, "d" * 180])
    assert limit is not None and limit >= 400
    assert channel_limit(["short", "rows"]) is None


def test_applying_a_contract_keeps_whatever_the_rows_already_declared():
    rows = [
        {
            "id": f"r{index}",
            "input": f"Where is order A-{index}000?",
            "expected": f"Order A-{index}000 ships tomorrow, thanks for your patience.",
            "graders": ["token_f1"],
        }
        for index in range(1, 6)
    ]
    done = apply_requirements(rows, "reply")
    assert all("token_f1" in row["graders"] for row in done)
    assert all("contains_all" in row["graders"] for row in done)
    # And the checkable requirement, not the similarity, is what the report
    # will put on its front.
    assert {headline_grader(row["graders"]) for row in done} == {"contains_all"}


@pytest.mark.parametrize(
    "slug",
    [
        spec["name"].split(":", 1)[1]
        for spec in yaml.safe_load(CATALOGUE.read_text())["sets"]
        if spec.get("contract")
    ],
)
def test_every_bundled_drafting_row_holds_a_contract_its_own_reference_meets(slug: str):
    rows = load_jsonl(BUSINESS / f"{slug}.jsonl")
    assert rows
    for row in rows:
        context = GradeContext(
            output=str(row.expected), expected=row.expected, options=row.grader_options
        )
        for name in row.graders:
            if name in REFERENCE_OVERLAP_GRADERS:
                continue
            score = get_grader(name)(context)
            assert score is None or score >= 1.0, f"{row.id}: reference fails its own {name}"


def test_the_templated_support_corpus_is_no_longer_scored_by_word_overlap():
    """The set the whole exercise started from.

    Its floor was 0.63 — an answer to a different ticket scored 0.63 — so the
    number on the front of a report about it said nothing. It now reports
    whether the reply carried the order reference back.
    """
    rows = json.loads(
        "["
        + ",".join(
            line for line in (BUSINESS / "support-reply.jsonl").read_text().splitlines() if line
        )
        + "]"
    )
    heads = {headline_grader(row["graders"]) for row in rows}
    assert "contains_all" in heads
    assert sum(1 for row in rows if headline_grader(row["graders"]) == "token_f1") <= 2


def test_adding_a_contract_never_removes_the_only_meaning_grader_a_row_had():
    """The regression this caught, kept caught.

    Rows arrive from an upload naming no graders at all, and are scored by
    whatever their shape implies. Writing only the contract onto them would have
    left rows that list `forbidden_content` and `length_limit` and nothing that
    speaks for correctness — and because a row that lists graders is never
    inferred for again, the quality number would have vanished with no sign of
    where it went. The inferred choice is written down alongside instead.
    """
    rows = [
        {"id": f"r{index}", "input": f"ticket {index}", "expected": f"answer {index} " * 6}
        for index in range(5)
    ]
    done = apply_requirements(rows, "reply")
    assert all("token_f1" in row["graders"] for row in done)
    assert all(headline_grader(row["graders"]) == "token_f1" for row in done)
