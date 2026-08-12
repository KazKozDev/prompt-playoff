"""Build entity-extraction-hard.jsonl (200 examples).

Every example is decidable from the rules in docs/datasets/entity-extraction-hard.md.
Ambiguity that a rule cannot settle would make the gold arbitrary, so each case
here targets one rule a naive prompt gets wrong.

The first 40 are hand-written. The rest come from generate_hard_examples.py,
where the gold answer follows from how the sentence was constructed — 200
hand-labelled rows would be 200 chances to mislabel one.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from generate_hard_examples import generate  # noqa: E402

TARGET = 200

SCHEMA = {
    "type": "object",
    "properties": {
        "people": {"type": "array", "items": {"type": "string"}},
        "places": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["people", "places"],
    "additionalProperties": False,
}

# (id, tags, input, people, places)
ROWS = [
    # --- rule 1: a title attached to a name is part of the name ------------- #
    ("hard-001", ["title"], "Captain Orin refused to sail past Veyr.", ["Captain Orin"], ["Veyr"]),
    (
        "hard-002",
        ["title", "multi"],
        "Doctor Aleksei Varga met Nadia Ilic in Trieste.",
        ["Doctor Aleksei Varga", "Nadia Ilic"],
        ["Trieste"],
    ),
    (
        "hard-003",
        ["title", "proper-place"],
        "Queen Elara remained in the Glass Citadel all winter.",
        ["Queen Elara"],
        ["Glass Citadel"],
    ),
    (
        "hard-004",
        ["title", "common-noun-place"],
        "Brother Tomas walked from the abbey at Saint-Loup to the harbour at Marseille.",
        ["Brother Tomas"],
        ["Saint-Loup", "Marseille"],
    ),
    (
        "hard-005",
        ["title", "multi"],
        "Sergeant Idris Pell reported to Colonel Wray outside Ashfall.",
        ["Sergeant Idris Pell", "Colonel Wray"],
        ["Ashfall"],
    ),
    # --- rule 2: a role without a name is not a person --------------------- #
    ("hard-006", ["role-only"], "The innkeeper refused to serve them in Kesh.", [], ["Kesh"]),
    ("hard-007", ["role-only"], "Her brother had already left for Lorne.", [], ["Lorne"]),
    (
        "hard-008",
        ["role-only"],
        "The harbourmaster and two clerks waited at Marseille.",
        [],
        ["Marseille"],
    ),
    ("hard-009", ["role-only"], "A courier from the north reached Veyr before dawn.", [], ["Veyr"]),
    (
        "hard-010",
        ["role-only", "empty"],
        "The old woman who kept the lighthouse never gave it a name.",
        [],
        [],
    ),
    # --- rule 3: common nouns are not places, proper names are ------------- #
    (
        "hard-011",
        ["common-noun-place"],
        "They crossed the river before reaching Trieste.",
        [],
        ["Trieste"],
    ),
    (
        "hard-012",
        ["common-noun-place"],
        "Mara slept in the abbey, then rode to Saint-Loup.",
        ["Mara"],
        ["Saint-Loup"],
    ),
    (
        "hard-013",
        ["proper-place"],
        "The Glass Citadel stood above the old town.",
        [],
        ["Glass Citadel"],
    ),
    (
        "hard-014",
        ["common-noun-place"],
        "Pell waited at the harbour in Port Lorne.",
        ["Pell"],
        ["Port Lorne"],
    ),
    (
        "hard-015",
        ["common-noun-place"],
        "The valley below Ashfall was empty that season.",
        [],
        ["Ashfall"],
    ),
    # --- rule 4: an organisation is neither a person nor a place ----------- #
    (
        "hard-016",
        ["organisation"],
        "The Verity Consortium opened an office in Trieste.",
        [],
        ["Trieste"],
    ),
    (
        "hard-017",
        ["organisation"],
        "Sera left the Kesh Mining Guild and moved to Lorne.",
        ["Sera"],
        ["Lorne"],
    ),
    (
        "hard-018",
        ["organisation", "same-token"],
        "Orin signed with the Ashfall Company before he ever saw Ashfall.",
        ["Orin"],
        ["Ashfall"],
    ),
    ("hard-019", ["organisation"], "The Glass Citadel Trust met in Veyr.", [], ["Veyr"]),
    # --- rule 5: derived adjectives are not mentions ----------------------- #
    ("hard-020", ["demonym"], "The Veyrish delegation arrived without Mara.", ["Mara"], []),
    ("hard-021", ["demonym"], "Kesh-born traders avoided Marseille that year.", [], ["Marseille"]),
    ("hard-022", ["demonym"], "Elara spoke with a Triestine accent.", ["Elara"], []),
    (
        "hard-023",
        ["demonym", "attributive"],
        "The smoke from Ashfall drifted over Lorne.",
        [],
        ["Ashfall", "Lorne"],
    ),
    # --- rule 6: a named fictional being is still a person ----------------- #
    (
        "hard-024",
        ["fictional"],
        "The Hollow King was a story children told in Ashfall.",
        ["The Hollow King"],
        ["Ashfall"],
    ),
    (
        "hard-025",
        ["fictional"],
        "Sailors in Veyr swore the Drowned Man walked the pier.",
        ["the Drowned Man"],
        ["Veyr"],
    ),
    (
        "hard-026",
        ["fictional", "title"],
        "Children in Kesh still leave bread for Saint Alba.",
        ["Saint Alba"],
        ["Kesh"],
    ),
    # --- rule 7: absence and negation do not remove a mention -------------- #
    ("hard-027", ["negation"], "No one had seen Mara since the fire at Veyr.", ["Mara"], ["Veyr"]),
    ("hard-028", ["negation"], "Orin never reached Marseille.", ["Orin"], ["Marseille"]),
    (
        "hard-029",
        ["negation", "multi"],
        "Neither Pell nor Idris returned to Lorne.",
        ["Pell", "Idris"],
        ["Lorne"],
    ),
    ("hard-030", ["negation"], "There was no road out of Kesh that winter.", [], ["Kesh"]),
    # --- rule 8: repeated mentions collapse to one ------------------------- #
    (
        "hard-031",
        ["duplicate"],
        "Mara left Veyr, and Mara did not look back at Veyr.",
        ["Mara"],
        ["Veyr"],
    ),
    (
        "hard-032",
        ["duplicate"],
        "Orin wrote from Trieste; Orin wrote again from Trieste.",
        ["Orin"],
        ["Trieste"],
    ),
    (
        "hard-033",
        ["duplicate"],
        "Ashfall, always Ashfall — Sera could not leave Ashfall.",
        ["Sera"],
        ["Ashfall"],
    ),
    # --- rule 9: the same token can be both, decided by context ------------ #
    (
        "hard-034",
        ["same-token", "title"],
        "Captain Lorne refused to leave Port Lorne.",
        ["Captain Lorne"],
        ["Port Lorne"],
    ),
    ("hard-035", ["same-token"], "Wray met Sera at Wray Point.", ["Wray", "Sera"], ["Wray Point"]),
    (
        "hard-036",
        ["same-token"],
        "Kesh, the youngest of the three, had never seen Kesh.",
        ["Kesh"],
        ["Kesh"],
    ),
    ("hard-037", ["same-token"], "They buried Alba at Saint-Loup.", ["Alba"], ["Saint-Loup"]),
    # --- rule 10: nothing named means empty arrays, not omitted keys ------- #
    ("hard-038", ["empty"], "Nothing happened that day.", [], []),
    ("hard-039", ["empty"], "The roads were empty and the sea was grey.", [], []),
    ("hard-040", ["empty"], "Rain, then more rain.", [], []),
]


def all_rows() -> list[tuple[str, list[str], str, list[str], list[str]]]:
    """Hand-written seeds first, then generated rows up to TARGET."""
    rows = [
        (row_id, [*tags, "handwritten"], text, people, places)
        for row_id, tags, text, people, places in ROWS
    ]
    taken = {text for _, _, text, _, _ in rows}
    index = len(rows)
    for tags, text, people, places in generate(TARGET * 3):
        if len(rows) >= TARGET:
            break
        if text in taken:
            continue
        taken.add(text)
        index += 1
        rows.append((f"hard-{index:03d}", [*tags, "generated"], text, people, places))
    if len(rows) < TARGET:
        raise SystemExit(f"only produced {len(rows)} of {TARGET} distinct examples")
    return rows


def main() -> None:
    out = Path("src/prompt_playoff/data/datasets/entity-extraction-hard.jsonl")
    lines = []
    for row_id, tags, text, people, places in all_rows():
        # A gold value that is not verbatim in the input cannot be "copied", so
        # it would penalise the model for the annotator's paraphrase.
        for value in [*people, *places]:
            assert value in text, f"{row_id}: {value!r} is not verbatim in the input"
        assert len(set(people)) == len(people), f"{row_id}: duplicate person"
        assert len(set(places)) == len(places), f"{row_id}: duplicate place"
        lines.append(
            json.dumps(
                {
                    "id": row_id,
                    "input": text,
                    "expected": {"people": people, "places": places},
                    "response_schema": SCHEMA,
                    "tags": tags,
                },
                ensure_ascii=False,
            )
        )
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {len(lines)} examples to {out}")

    from collections import Counter

    rows = all_rows()
    counts = Counter(tag for _, tags, _, _, _ in rows for tag in tags)
    print("tags:", dict(sorted(counts.items())))
    empty = sum(1 for _, _, _, p, q in rows if not p and not q)
    print(f"fully empty: {empty}, with people: {sum(1 for r in rows if r[3])}")


if __name__ == "__main__":
    main()
