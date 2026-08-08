"""Build support-classification.jsonl (150 examples).

The label follows from which template produced the ticket, so it cannot drift
from the category definitions the way hand-labelling 150 tickets would.

The interesting third of the set is the boundary cases: tickets that mention
billing but describe broken behaviour (a bug), or ask for a login feature that
does not exist yet (a feature request, not an account problem). A prompt that
matches on keywords gets those wrong, which is the point.
"""

from __future__ import annotations

import json
import random
from collections import Counter
from pathlib import Path

LABELS = ["billing", "bug", "feature_request", "account"]

BOUNDARIES = (
    "billing covers charges, refunds, invoices and pricing. "
    "bug covers something that exists but is broken. "
    "feature_request covers something that does not exist yet. "
    "account covers login, permissions, seats and profile data. "
    "When a ticket mentions a billing document but describes broken behaviour, it is a bug. "
    "When a ticket asks for a login capability that does not exist yet, it is a feature_request."
)

SCHEMA = {
    "type": "object",
    "properties": {"label": {"type": "string", "enum": LABELS}},
    "required": ["label"],
    "additionalProperties": False,
}

PRODUCTS = ["the dashboard", "the export tool", "the mobile app", "the API", "the report builder"]
BROWSERS = ["Safari", "Firefox", "Edge", "Chrome"]
PLANS = ["the Team plan", "the Pro plan", "the annual plan", "the starter plan"]

# (label, tags, template) — {p} product, {b} browser, {n} plan
TEMPLATES: list[tuple[str, list[str], str]] = [
    # --- billing: money moved, or should have -------------------------------- #
    (
        "billing",
        ["plain"],
        "I was charged twice for the same month and nobody has replied to my email.",
    ),
    (
        "billing",
        ["plain"],
        "We downgraded from {n} three weeks ago but the old price is still being taken.",
    ),
    ("billing", ["plain"], "Can I get a refund for the period after we cancelled?"),
    ("billing", ["plain"], "The invoice lists five seats, we only ever had three."),
    (
        "billing",
        ["plain"],
        "How is usage on {n} actually counted? The total does not match my estimate.",
    ),
    (
        "billing",
        ["plain"],
        "Our card expired and now the account is past due. How do we settle it?",
    ),
    (
        "billing",
        ["plain"],
        "Please send a VAT invoice for last quarter, finance needs it for the audit.",
    ),
    (
        "billing",
        ["plain"],
        "We were promised a discount when we signed, but the first charge was full price.",
    ),
    # --- bug: exists, broken ------------------------------------------------- #
    ("bug", ["plain"], "The export button on {p} spins forever in {b} but works fine elsewhere."),
    ("bug", ["plain"], "{p} shows yesterday's numbers no matter which date range I pick."),
    ("bug", ["plain"], "Saving a filter on {p} throws a red error and loses everything I typed."),
    ("bug", ["plain"], "Search on {p} returns nothing for terms I can see on the page."),
    ("bug", ["plain"], "{p} logs me out every few minutes since the last update."),
    ("bug", ["plain"], "Uploading a file over 10MB to {p} fails silently, with no message at all."),
    ("bug", ["plain"], "The chart on {p} renders on top of the sidebar in {b}."),
    ("bug", ["plain"], "Sorting by date on {p} puts December before January."),
    # --- feature_request: does not exist yet --------------------------------- #
    ("feature_request", ["plain"], "Could you add a dark theme? Reading {p} at night is painful."),
    (
        "feature_request",
        ["plain"],
        "We would like scheduled email reports, weekly, straight to the team.",
    ),
    (
        "feature_request",
        ["plain"],
        "Any chance of a bulk edit on {p}? Doing it row by row takes hours.",
    ),
    (
        "feature_request",
        ["plain"],
        "It would help enormously if {p} could export to Parquet as well as CSV.",
    ),
    ("feature_request", ["plain"], "Please consider a webhook when a report finishes generating."),
    ("feature_request", ["plain"], "Is a Slack integration on the roadmap? We would use it daily."),
    (
        "feature_request",
        ["plain"],
        "We need custom fields on records — the fixed schema does not fit us.",
    ),
    # --- account: who you are and what you may do ---------------------------- #
    (
        "account",
        ["plain"],
        "My colleague left the company and I cannot remove her from the workspace.",
    ),
    ("account", ["plain"], "I am locked out after too many attempts. How long until it resets?"),
    (
        "account",
        ["plain"],
        "Can you move ownership of the workspace to me? The founder no longer works here.",
    ),
    ("account", ["plain"], "Two of my team see the admin menu and they should not."),
    ("account", ["plain"], "I need to change the email on my profile but the field is greyed out."),
    ("account", ["plain"], "We have five seats but only four people can sign in."),
    ("account", ["plain"], "How do I set someone to read-only across the whole workspace?"),
    # --- boundary: billing words, broken behaviour -> bug --------------------- #
    (
        "bug",
        ["boundary", "billing-words"],
        "The invoice PDF downloads as a zero-byte file, so I cannot forward it to finance.",
    ),
    (
        "bug",
        ["boundary", "billing-words"],
        "The billing page shows a spinner forever and never loads our payment history.",
    ),
    (
        "bug",
        ["boundary", "billing-words"],
        "Clicking 'download receipt' on {p} opens a blank tab in {b}.",
    ),
    (
        "bug",
        ["boundary", "billing-words"],
        "The price at checkout is right, but the confirmation email quotes a different number.",
    ),
    (
        "bug",
        ["boundary", "billing-words"],
        "Our usage counter resets to zero at random, so the projected bill is nonsense.",
    ),
    (
        "bug",
        ["boundary", "billing-words"],
        "The subscription page lists {n} twice and I cannot tell which one is active.",
    ),
    # --- boundary: login words, does not exist yet -> feature_request --------- #
    (
        "feature_request",
        ["boundary", "account-words"],
        "We would like SSO through Okta before we roll this out to the whole team.",
    ),
    (
        "feature_request",
        ["boundary", "account-words"],
        "Do you support SCIM provisioning? Adding users by hand does not scale for us.",
    ),
    (
        "feature_request",
        ["boundary", "account-words"],
        "Please add two-factor authentication — our security review flagged its absence.",
    ),
    (
        "feature_request",
        ["boundary", "account-words"],
        "Could permissions be per-project rather than workspace-wide? We need finer control.",
    ),
    (
        "feature_request",
        ["boundary", "account-words"],
        "An audit log of who signed in and when would satisfy our compliance team.",
    ),
    # --- boundary: asks about price, but wants a capability -> feature_request  #
    (
        "feature_request",
        ["boundary", "billing-words"],
        "Is there any plan that includes an on-premise deployment? Happy to pay more.",
    ),
    (
        "feature_request",
        ["boundary", "billing-words"],
        "We would upgrade tomorrow if {n} included an SLA. Does that exist anywhere?",
    ),
    # --- boundary: broken login -> account, not bug --------------------------- #
    (
        "account",
        ["boundary", "bug-words"],
        "The reset-password email never arrives, and support says my address is not on file.",
    ),
    (
        "account",
        ["boundary", "bug-words"],
        "My invite link says 'expired' but it was sent an hour ago and I never opened it.",
    ),
    (
        "account",
        ["boundary", "bug-words"],
        "After the migration my old login stopped working and the new one has no permissions.",
    ),
    # --- boundary: feature words, but it exists and is broken -> bug ---------- #
    (
        "bug",
        ["boundary", "feature-words"],
        "The dark theme you shipped last month makes half the text unreadable in {b}.",
    ),
    (
        "bug",
        ["boundary", "feature-words"],
        "Scheduled reports arrive empty, though the same report is fine when run manually.",
    ),
    (
        "bug",
        ["boundary", "feature-words"],
        "The Slack integration posts every message twice since Tuesday.",
    ),
]

SUFFIXES = [
    "",
    " Any idea what is going on?",
    " This is blocking us today.",
    " Thanks in advance.",
    " Let me know what you need from our side.",
    " Third time I am writing about this.",
]


def build(count: int = 150, seed: int = 20260808) -> list[dict]:
    rng = random.Random(seed)
    rows: list[dict] = []
    seen: set[str] = set()
    attempts = 0

    while len(rows) < count and attempts < count * 200:
        attempts += 1
        label, tags, template = rng.choice(TEMPLATES)
        text = (
            template.replace("{p}", rng.choice(PRODUCTS))
            .replace("{b}", rng.choice(BROWSERS))
            .replace("{n}", rng.choice(PLANS))
        ) + rng.choice(SUFFIXES)
        if text in seen:
            continue
        seen.add(text)
        rows.append(
            {
                "id": f"cls-{len(rows) + 1:03d}",
                "input": text,
                "expected": label,
                "response_schema": SCHEMA,
                "graders": ["label_accuracy", "allowed_labels", "json_validity"],
                "grader_options": {"labels": LABELS},
                "variables": {"label_set": ", ".join(LABELS), "boundaries": BOUNDARIES},
                "tags": tags,
            }
        )
    if len(rows) < count:
        raise SystemExit(f"template bank exhausted at {len(rows)} of {count}")
    return rows


def main() -> None:
    rows = build()
    out = Path("src/prompt_selector/data/datasets/support-classification.jsonl")
    out.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8"
    )
    print(f"wrote {len(rows)} examples to {out}")

    labels = Counter(row["expected"] for row in rows)
    print("labels:", dict(sorted(labels.items())))
    boundary = sum(1 for row in rows if "boundary" in row["tags"])
    print(f"boundary cases: {boundary} ({boundary * 100 // len(rows)}%)")
    # Every label must be reachable, or the set silently tests three categories.
    assert set(labels) == set(LABELS), f"missing labels: {set(LABELS) - set(labels)}"
    assert min(labels.values()) >= 15, f"a label is too rare: {labels}"


if __name__ == "__main__":
    main()
