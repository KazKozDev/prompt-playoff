"""Judging a whole set, not one pair at a time."""

from __future__ import annotations

import asyncio

from prompt_playoff.domain import ModelProfile, ModelResult
from prompt_playoff.rubric import judge_rows

MODEL = ModelProfile(provider="ollama", model_id="judge-7b")
ROWS = [
    (f"r{index}", f"Where is order A-{index}?", f"answer {index}", f"reference {index}")
    for index in range(6)
]


def _judge(script):
    """A judge that answers from `script`, keyed by which slot it is shown."""
    calls = []

    async def generate(prompt, model, timeout_seconds=120):
        body = prompt.messages[1].content
        first = body.split("FIRST ANSWER:\n", 1)[1].split("\n\nSECOND ANSWER:", 1)[0]
        calls.append(first)
        return ModelResult(content=script(first), usage={})

    generate.calls = calls
    return generate


def test_the_prompt_wins_when_the_judge_picks_it_whichever_slot_it_is_in():
    """Blinding is only worth having if the score follows the answer, not the slot."""
    judge = _judge(
        lambda first: (
            '{"winner": "first", "rationale": "clearer"}'
            if first.startswith("answer")
            else '{"winner": "second", "rationale": "clearer"}'
        )
    )
    verdict = asyncio.run(judge_rows(ROWS, rubric=["clarity"], judge_model=MODEL, generate=judge))
    assert verdict.wins == 6
    assert verdict.win_rate == 1.0
    # And the shuffle really did move it around, or the test proved nothing.
    assert {row.shown_as for row in verdict.rows} == {"first", "second"}


def test_ties_count_as_half_and_the_summary_says_so():
    answers = iter(
        ['{"winner": "tie", "rationale": ""}'] * 3 + ['{"winner": "first", "rationale": ""}'] * 3
    )
    judge = _judge(lambda first: next(answers))
    verdict = asyncio.run(judge_rows(ROWS, rubric=["tone"], judge_model=MODEL, generate=judge))
    assert verdict.ties == 3
    assert verdict.win_rate == round((verdict.wins + 1.5) / 6, 4)
    assert "counting ties as half" in verdict.summary


def test_one_unreadable_reply_does_not_decide_the_other_rows():
    """A judge that returned nonsense on row three has said nothing about row
    three — and nothing about the rest, which is the part that used to be lost."""
    seen = {"n": 0}

    def script(first):
        seen["n"] += 1
        return "not json" if seen["n"] == 3 else '{"winner": "first", "rationale": ""}'

    verdict = asyncio.run(
        judge_rows(ROWS, rubric=["clarity"], judge_model=MODEL, generate=_judge(script))
    )
    assert verdict.errors == 1
    assert len(verdict.rows) == 6
    assert verdict.win_rate is not None  # the other five still decided something


def test_a_judge_that_never_answered_reports_no_rate_rather_than_zero():
    verdict = asyncio.run(
        judge_rows(ROWS, rubric=["clarity"], judge_model=MODEL, generate=_judge(lambda f: "{"))
    )
    assert verdict.errors == 6
    assert verdict.win_rate is None
    assert verdict.summary == "No row was judged."


def test_the_same_seed_puts_the_same_answer_in_the_same_slot():
    """A rerun that disagrees with itself should be the judge changing its mind,
    not the harness reshuffling underneath it."""
    judge = _judge(lambda first: '{"winner": "tie", "rationale": ""}')
    first = asyncio.run(judge_rows(ROWS, rubric=["x"], judge_model=MODEL, generate=judge))
    second = asyncio.run(judge_rows(ROWS, rubric=["x"], judge_model=MODEL, generate=judge))
    assert [row.shown_as for row in first.rows] == [row.shown_as for row in second.rows]


def test_a_verdict_stays_a_model_opinion_until_a_person_accepts_it():
    judge = _judge(lambda first: '{"winner": "first", "rationale": ""}')
    verdict = asyncio.run(judge_rows(ROWS, rubric=["x"], judge_model=MODEL, generate=judge))
    assert verdict.status == "pending_human_review"
