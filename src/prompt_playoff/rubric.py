"""Judging a whole set against its reference answers, instead of one pair at a time.

Some requirements cannot be decided by a rule. Whether an explanation lands,
whether a reply reads as an apology or as a brush-off — no `contains_all` sees
that, and pretending otherwise is how a checklist starts standing in for
judgement. For those, the tool asks a different model, blind.

What was missing was scale. The judge could compare two answers, once, and put
the verdict in a queue for a person — useful for settling an argument about one
example, useless for the question anybody actually has, which is whether the
prompt is better across the set. This runs the same blind comparison over every
row of a recorded run, against the reference answer that row already carries,
and reports the share of rows the prompt won.

Three things this is not, said here because each of them has been assumed of a
number like it:

* It is not a benchmark score. A model produced it, so it lands in the review
  queue as one batch and stays a model's opinion until a person accepts it.
* It is not gateable in CI. `prompt-playoff check` enforces deterministic
  graders only; a bar defended by a model's mood on the day is not a bar.
* It is not a win over "the right answer". The reference is one answer a person
  wrote, so a win rate of 0.5 means the prompt writes about as well as that
  person did — not that half its answers were wrong.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import Literal

from pydantic import BaseModel, Field

from prompt_playoff.domain import CompiledPrompt, Message, ModelProfile

#: Compared answers, not scored ones. A model asked "how good is this, 0 to 10"
#: answers about the length and confidence of the text in front of it; asked
#: "which of these two is better" it has something to hold each against. The
#: reference answer is the other side, and which side is which is hidden.
Generate = Callable[[CompiledPrompt, ModelProfile, float], Awaitable[object]]


class RowVerdict(BaseModel):
    example_id: str
    outcome: Literal["win", "tie", "loss", "error"]
    rationale: str = ""
    #: Which slot the prompt's answer occupied, so a reader can check the
    #: blinding held rather than take it on trust.
    shown_as: Literal["first", "second"] = "first"
    error: str | None = None


class RubricVerdict(BaseModel):
    judge_model: str
    rubric: list[str]
    rows: list[RowVerdict]
    wins: int = 0
    ties: int = 0
    losses: int = 0
    errors: int = 0
    #: Wins plus half the ties, over the rows that produced a verdict. The usual
    #: reading of a pairwise contest, and undefined rather than zero when every
    #: row errored — a judge that never answered has said nothing.
    win_rate: float | None = None
    #: Present when the judge shares a lineage with a model that wrote the
    #: answers, which blinding cannot fix and this cannot correct for.
    self_preference_warning: str | None = None
    status: Literal["pending_human_review"] = "pending_human_review"

    @property
    def summary(self) -> str:
        if self.win_rate is None:
            return "No row was judged."
        return (
            f"{self.judge_model} preferred these answers to the reference on "
            f"{self.wins} of {len(self.rows) - self.errors} rows "
            f"({self.win_rate:.0%} counting ties as half)."
        )


class JudgeReading(BaseModel):
    """The reply as it arrives. Only the choice is read; no score is asked for.

    A number would have to be normalised, defended and eventually gated on. The
    choice is the part a judge is actually good at, and it needs none of that.
    """

    winner: Literal["first", "second", "tie"]
    rationale: str = Field(default="", max_length=2000)


def judge_prompt(rubric: list[str], text: str, first: str, second: str) -> CompiledPrompt:
    return CompiledPrompt(
        technique_id="rubric-judge",
        stage="judge",
        messages=[
            Message(
                role="system",
                content=(
                    "You are an impartial evaluator. Apply only the rubric. One of these "
                    "answers is a reference and one is a candidate; you are not told which, "
                    "and guessing is not part of the task. Choose the better answer, or "
                    "'tie' when the rubric cannot separate them. Return the requested JSON."
                ),
            ),
            Message(
                role="user",
                content=(
                    f"INPUT:\n{text}\n\nRUBRIC:\n- "
                    + "\n- ".join(rubric)
                    + f"\n\nFIRST ANSWER:\n{first}\n\nSECOND ANSWER:\n{second}"
                ),
            ),
        ],
        response_schema=JudgeReading.model_json_schema(),
        generation_options={"temperature": 0},
    )


async def judge_rows(
    rows: list[tuple[str, str, str, str]],
    *,
    rubric: list[str],
    judge_model: ModelProfile,
    generate: Generate,
    seed: int = 20260816,
    timeout_seconds: float = 120,
    self_preference_warning: str | None = None,
) -> RubricVerdict:
    """Judge every row blind. ``rows`` are ``(id, input, answer, reference)``.

    The order of the two answers is shuffled per row from one seed, so the same
    set judged twice puts the same answer in the same slot — a rerun that
    disagrees with itself is then the judge changing its mind, which is worth
    knowing, and not the harness reshuffling underneath it.

    One failed row does not end the run: a judge that returns unreadable JSON on
    row nine has said nothing about row nine and nothing about the other fifty.
    """
    rng = random.Random(seed)
    verdicts: list[RowVerdict] = []
    for example_id, text, answer, reference in rows:
        answer_first = rng.random() < 0.5
        first, second = (answer, reference) if answer_first else (reference, answer)
        try:
            result = await generate(
                judge_prompt(rubric, text, first, second), judge_model, timeout_seconds
            )
            read = JudgeReading.model_validate_json(getattr(result, "content", ""))
        except Exception as exc:  # a judge that cannot answer is not a loss
            verdicts.append(
                RowVerdict(
                    example_id=example_id,
                    outcome="error",
                    shown_as="first" if answer_first else "second",
                    error=str(exc) or type(exc).__name__,
                )
            )
            await asyncio.sleep(0)
            continue
        if read.winner == "tie":
            outcome: Literal["win", "tie", "loss"] = "tie"
        else:
            chose_first = read.winner == "first"
            outcome = "win" if chose_first == answer_first else "loss"
        verdicts.append(
            RowVerdict(
                example_id=example_id,
                outcome=outcome,
                rationale=read.rationale,
                shown_as="first" if answer_first else "second",
            )
        )
        await asyncio.sleep(0)

    wins = sum(1 for item in verdicts if item.outcome == "win")
    ties = sum(1 for item in verdicts if item.outcome == "tie")
    losses = sum(1 for item in verdicts if item.outcome == "loss")
    errors = sum(1 for item in verdicts if item.outcome == "error")
    decided = wins + ties + losses
    return RubricVerdict(
        judge_model=judge_model.model_id,
        rubric=list(rubric),
        rows=verdicts,
        wins=wins,
        ties=ties,
        losses=losses,
        errors=errors,
        win_rate=round((wins + ties / 2) / decided, 4) if decided else None,
        self_preference_warning=self_preference_warning,
    )
