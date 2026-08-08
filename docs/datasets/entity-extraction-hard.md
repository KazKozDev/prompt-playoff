# entity-extraction-hard

200 examples, built so that a naive prompt fails on something specific rather
than on noise.

The first **40 are hand-written**. The remaining 160 are **generated
compositionally** from a template bank (`scripts/generate_hard_examples.py`):
the gold answer follows from how the sentence was constructed, so it cannot
drift from the rules. Hand-labelling 200 rows would be 200 chances to mislabel
one. Every row carries a `handwritten` or `generated` tag.

Every gold value is **verbatim in the input** — the build script asserts it — so
a model is never penalised for failing to reproduce an annotator's paraphrase.
Duplicates are collapsed, and the generator is seeded, so the file is
reproducible byte for byte.

## Annotation rules

A gold answer is arbitrary unless a rule decides it. These are the rules; each
one is what a given group of examples tests.

1. **A title attached to a name is part of the name.** `Captain Orin`,
   `Doctor Aleksei Varga`, `Saint Alba`. Not `Orin`.
2. **A role without a name is not a person.** `the innkeeper`, `her brother`,
   `two clerks`, `a courier` produce nothing.
3. **Common nouns are not places; proper names are.** `the abbey`,
   `the harbour`, `the river`, `the valley` produce nothing. `Glass Citadel`,
   `Port Lorne`, `Saint-Loup` do.
4. **An organisation is neither a person nor a place**, even when a place name
   is inside it. `the Kesh Mining Guild` yields no place; `the Ashfall Company`
   yields none, but a bare `Ashfall` later in the same sentence does.
5. **A derived adjective is not a mention.** `Veyrish`, `Triestine`,
   `Kesh-born` produce nothing. A bare place name used attributively
   (`the smoke from Ashfall`) still counts.
6. **A named fictional or mythical being is a person.** `The Hollow King`,
   `the Drowned Man`, `Saint Alba`.
7. **Absence and negation do not remove a mention.** "No one had seen Mara",
   "Orin never reached Marseille" — both names count.
8. **Repeated mentions collapse to one entry.**
9. **The same token can be both**, decided by context: in
   "Kesh, the youngest of the three, had never seen Kesh" the first is a person
   and the second a place, so `Kesh` appears in both arrays.
10. **Nothing named means empty arrays**, never omitted keys.

## Composition

| Group | Examples | Rule |
|---|---|---|
| `title` | 47 | 1 |
| `role-only` | 25 | 2 |
| `common-noun-place`, `proper-place` | 26 | 3 |
| `organisation` | 28 | 4 |
| `demonym`, `attributive` | 26 | 5 |
| `fictional` | 12 | 6 |
| `negation` | 35 | 7 |
| `duplicate` | 15 | 8 |
| `same-token` | 27 | 9 |
| `empty` | 5 | 10 |
| `mixed` | 12 | two rules colliding in one sentence |

Tags overlap, so the column sums past 200. 147 examples contain at least one
person; 8 are entirely empty. The empty ones matter: a prompt that improves
recall by guessing loses precision there, and `field_f1` shows it.

Measured baseline (`structured.schema-first`, `qwen2.5:7b`): **quality 0.813**,
reliability 1.000, 173 tokens, 0.79 s per example.

## What the optimizer is expected to discover

None of these rules appear in any technique's default prompt. They are exactly
the kind of thing a reflective optimizer should recover from observed failures —
"copy the title with the name", "do not treat the guild as a place". That makes
this dataset a test of the optimizer, not only of the model.

## Rebuilding

The source of truth is `scripts/build_hard_dataset.py`, which validates the
verbatim and duplicate constraints before writing the JSONL.
