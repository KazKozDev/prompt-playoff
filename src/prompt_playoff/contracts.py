"""Requirements a rule can check, derived from rows that carry only a reference.

A drafting corpus arrives as pairs: the thing that came in, and the one answer a
person wrote. That is enough to compute a similarity and nothing else, which is
how a whole shelf of business sets ended up scored by word overlap — a number
that on templated support replies gives an answer to the wrong ticket 0.63.

What is missing is not a better similarity. It is the requirements the work
actually has, none of which need a reference answer to decide:

    the identifier in the question has to come back in the reply
    the draft may not ship with ``{{Order Number}}`` still in it
    it has to fit the channel

Those are derived here, from the rows themselves, deterministically. Nothing is
invented: a needle is required only when the incoming text and the human answer
both contain it, so the requirement is one a person already met on that row.
The derivation runs at fetch time, so a re-downloaded corpus arrives with its
contract attached rather than acquiring one by hand-editing.
"""

from __future__ import annotations

import re
from typing import Any

#: Text a draft may never carry into production, whatever it says otherwise.
#:
#: These are not style. `{{Order Number}}` in a sent reply is a template that
#: never got filled; "As an AI language model" is the assistant talking about
#: itself to a customer. Both are decidable without knowing what the right
#: answer was, which is what makes them enforceable on open-ended work — and
#: `business:support-reply` needs them most, because its own reference answers
#: are templates: word overlap there pays a model for reproducing the very
#: placeholder that makes the answer unsendable.
UNFINISHED_DRAFT_PATTERNS = (
    r"\{\{[^}\n]{1,40}\}\}",
    r"\[INSERT[^\]\n]{0,40}\]",
    r"\[YOUR [A-Z ]{1,30}\]",
    r"\bTODO\b",
    r"\bLorem ipsum\b",
    r"\bas an AI (?:language )?model\b",
)

#: An identifier: an order, ticket, invoice or case number. Deliberately narrow.
#: A reply need not repeat the words of the question, but a reply about order
#: A-4471 that does not say A-4471 is answering about nothing, and that is true
#: however the sentence around it is worded.
#:
#: The third alternative is a template token, and it is here because of what
#: `business:support-reply` turned out to be: every question in it asks about
#: order ``{{Order Number}}`` and every answer says it back. In that corpus the
#: template token *is* the identifier, so requiring it is the same requirement —
#: carry the order reference back — written in the vocabulary the rows use.
_IDENTIFIER = re.compile(r"\b(?:[A-Z]{1,4}[-–/]\d{2,}[\w-]*|\d{6,})\b|\{\{[^}\n]{1,40}\}\}")

#: A fact a summary is expected to preserve: a date, a quantity, a share, a sum
#: of money, or a name of two or more capitalised words.
_FACTS = (
    re.compile(r"\b\d{1,3}(?:[.,]\d+)?\s?%"),
    re.compile(r"[$€£]\s?\d[\d.,]*(?:\s?(?:million|billion|m|bn))?", re.IGNORECASE),
    re.compile(
        r"\b\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\b|\b(?:January|February|March|April|May|June|July|"
        r"August|September|October|November|December)\s+\d{1,2}\b"
    ),
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(r"\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,}){1,3}\b"),
)

#: How many needles one row may require. A summary that has to reproduce nine
#: names is being asked to be a transcript; the first few are the test.
MAX_NEEDLES = 4
#: Below this, the row has nothing worth requiring and gets no `contains_all` —
#: a one-needle requirement is a coin toss dressed as a contract.
MIN_NEEDLES = 2


def _shared(text: str, expected: str, patterns: tuple[re.Pattern[str], ...]) -> list[str]:
    """Matches that occur in both the incoming text and the human answer.

    Both sides matter. A match only in the input is a fact the person chose to
    drop, and requiring it would score the model against a summary nobody
    wrote; a match only in the answer is that person's own addition.
    """
    found: list[str] = []
    for pattern in patterns:
        for match in pattern.findall(text):
            item = match if isinstance(match, str) else match[0]
            item = item.strip()
            if len(item) > 2 and item in expected and item not in found:
                found.append(item)
    return found


def requirements_for(
    text: str,
    expected: str,
    *,
    kind: str,
    max_chars: int | None = None,
) -> tuple[list[str], dict[str, Any]]:
    """The graders and options this one row can honestly be held to.

    ``kind`` is ``"reply"`` — an answer to somebody, which has to carry back the
    identifier it was asked about — or ``"summary"``, which has to preserve the
    facts the human summary preserved. Anything else gets the checks that apply
    to any draft at all.
    """
    # A pattern the incoming text already contains is not an unfinished draft:
    # it is the question's own wording, and the answer is allowed — often
    # required — to carry it back. Forbidding it would fail the human reference
    # itself, which is the exact species of trap this module exists to remove.
    forbidden = [
        pattern
        for pattern in UNFINISHED_DRAFT_PATTERNS
        if not re.search(pattern, text, re.IGNORECASE)
    ]
    graders = ["forbidden_content"] if forbidden else []
    options: dict[str, Any] = {"forbidden_patterns": forbidden} if forbidden else {}
    if max_chars:
        graders.append("length_limit")
        options["max_chars"] = int(max_chars)

    patterns = (_IDENTIFIER,) if kind == "reply" else _FACTS if kind == "summary" else ()
    needles = _shared(text, expected, patterns)[:MAX_NEEDLES] if patterns else []
    # An identifier is worth requiring on its own: there is only ever one, and
    # a reply that loses it is about no order at all.
    floor = 1 if kind == "reply" else MIN_NEEDLES
    if len(needles) >= floor:
        graders.append("contains_all")
        options["contains"] = needles
    return _kept(graders, options, expected)


def _kept(graders: list[str], options: dict[str, Any], expected: str) -> tuple[list[str], dict]:
    """Drop any requirement the human answer does not itself meet.

    The one rule that keeps this module from replacing a bad metric with a bad
    rule. A check the reference fails is not a requirement of the work — it is
    a guess about the work, and a model that answered as well as the person did
    would be marked wrong by it. That is the same defect as scoring a good
    reply 0.14 for choosing different words, arrived at from the other side.
    """
    from prompt_playoff.graders import GradeContext, get_grader

    context = GradeContext(output=expected, expected=expected, options=options)
    kept = [name for name in graders if (get_grader(name)(context) or 0.0) >= 1.0]
    if "contains_all" not in kept:
        options.pop("contains", None)
    if "forbidden_content" not in kept:
        options.pop("forbidden_patterns", None)
    if "length_limit" not in kept:
        options.pop("max_chars", None)
    return kept, options


def apply_requirements(rows: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    """Attach each row's derived contract, keeping whatever graders it declared.

    The similarity score stays where a set already had one: it is still a
    reasonable thing to watch drift on between two runs of the same prompt. It
    simply stops being the only thing the set can say, and — since a grader that
    decides something now outranks one that only measures resemblance — stops
    being the number on the front of the report.
    """
    from prompt_playoff.graders import default_graders

    limit = channel_limit([str(row.get("expected") or "") for row in rows])
    out: list[dict[str, Any]] = []
    for row in rows:
        expected = str(row.get("expected") or "")
        graders, options = requirements_for(
            str(row.get("input") or ""), expected, kind=kind, max_chars=limit
        )
        # A row that named nothing has its inferred graders written down here
        # rather than left to be re-inferred at run time. Two reasons, and the
        # second is the one that bites: the choice stops being invisible, and
        # adding a contract stops silently removing the only meaning grader the
        # row had — a row that lists graders is never inferred for again, so
        # writing only the contract would leave a set with no quality number at
        # all and no sign of where it went.
        declared = list(row.get("graders") or []) or default_graders(
            row.get("expected"), row.get("response_schema"), strict_json=False
        )
        merged = {**(row.get("grader_options") or {}), **options}
        item = {**row, "graders": [*declared, *[g for g in graders if g not in declared]]}
        if merged:
            item["grader_options"] = merged
        out.append(item)
    return out


def channel_limit(references: list[str]) -> int | None:
    """A length bound for the channel, read off what people actually wrote.

    Not a match to any reference: the longest human answer, doubled and rounded
    up. It fails a model that answers a support ticket with a page and a half —
    which happens, is unmistakable, and is otherwise scored as a good answer
    that merely worded things differently.
    """
    lengths = sorted(len(item) for item in references if item and item.strip())
    if len(lengths) < 4:
        return None
    longest = lengths[-1]
    step = 100 if longest < 1000 else 500
    return ((longest * 2) // step + 1) * step
