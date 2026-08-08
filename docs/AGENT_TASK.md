# Task brief for a coding agent

You are working on **prompt-selector**, a Python tool that picks a prompt
technique for a task, compiles the prompt that technique implies, measures it
against a real model, and can search for a better one. Everything it reports is
either a declared prior or a number measured on the user's own model, and it
always labels which.

Repository: `/Users/artemk/projects/prompt-selector`

```bash
source .venv/bin/activate        # already provisioned
pytest                           # 121 tests, must stay green
ruff check . && ruff format --check .
prompt-selector validate-registry --strict    # registry lint, must stay clean
```

Local models run through Ollama. `qwen2.5:7b` (fast, non-reasoning) is the
reference model; `llama3.2:3b` is the small one. Avoid `qwen3.5:9b` — it is a
thinking model and costs ~45 s per call.

---

## Conventions you must follow

1. **A new technique is one YAML file and no Python.** Files live in
   `src/prompt_selector/data/techniques/`. Read `docs/extending.md` first.
   `prompt-selector new-technique <id>` scaffolds one.
2. **Placeholders and block conditions come from closed vocabularies.** A typo
   is a lint error, not a literal `{brace}` reaching the model.
3. **Every validator must map to a real grader** in `graders.py`. A validator
   that cannot be computed is decoration and lint warns about it.
4. **`evidence_level` above `heuristic` requires a `source`** naming the paper.
   Lint enforces this. Verify any arXiv id you cite by resolving it against the
   arXiv API — a wrong citation is worse than none.
5. **Never execute model-generated code with `exec`/`eval`.** All execution goes
   through `sandbox.py`, a restricted AST interpreter. If it rejects something
   legitimate, extend the whitelist deliberately; do not widen the escape
   surface (no `ast.Attribute` as a general expression, no dunder names).
6. **Report failures rather than hiding them.** The codebase deliberately
   surfaces "this measurement is on 6 examples", "these demonstrations never
   reached the model", "the proposer returned nothing". Keep that habit.

---

## Context: what has been measured

Two findings shape the priorities below.

**Reasoning techniques help on computation and hurt on reading.** On entity
extraction, eleven of twelve published techniques scored *below* a plain prompt;
on GSM8K, zero-shot chain-of-thought scored 0.850 against the plain prompt's
0.250. See `docs/benchmarks/paper-techniques.md`.

**The native optimizer does not beat its baseline.** Widening the beam and
giving the proposer program structure, per-tag failure rates and prior attempts
all failed to produce a held-out gain. DSPy's MIPROv2 did (+0.064, repeat
verified). See `docs/benchmarks/native-vs-mipro.md`.

---

## Task 1 — datasets for the four uncovered task types (highest value)

The registry supports eight task types. Four have no dataset, so **16 techniques
have never been measured**:

| Task type | Techniques | Dataset |
|---|---:|---|
| translation | 4 | missing |
| summarization | 6 | missing |
| agents | 3 | missing |
| creative_writing | 3 | missing |
| research | 16 | `grounded-qa`, only 3 examples — effectively missing |

Build or import a dataset of **at least 100 examples** for each, in
`src/prompt_selector/data/datasets/*.jsonl`.

The hard part is grading, not collecting. Each dataset must be gradeable by
existing deterministic graders, or by a new one you add — **no LLM judge**, that
is a deliberate project constraint. Suggested approach per type:

- **translation** — source/target pairs plus a binding glossary; grade with
  `glossary_consistency` and `omission_check` (both exist, both need
  `grader_options`).
- **summarization** — documents with required facts; grade with `contains_all`
  and `length_limit`.
- **research** — extend `grounded-qa` to 100+; grade with `grounding_overlap`
  and `contains_all`. Include cases where the sources do *not* settle the
  question, so a confident wrong answer is punished.
- **agents** — tasks solvable with the `calculator` tool in `tools.py`, plus new
  deterministic tools you register there; grade with `tool_success` and
  `exact_match`.

Follow the pattern in `scripts/build_hard_dataset.py`: hand-write seed examples,
generate the rest compositionally so the gold answer follows from construction,
and assert the invariants (gold verbatim in the input where applicable, no
duplicates, deterministic seed). Document each dataset in `docs/datasets/`.

**Acceptance:** each new dataset has ≥100 examples, a doc stating its annotation
rules, and a recorded baseline (`prompt-selector benchmark`) showing the
baseline scores meaningfully below 1.0 — a dataset with no headroom cannot
distinguish techniques.

---

## Task 2 — make the optimizer append rules instead of rewriting blocks

`optimizer.py` mutates an instruction block by replacing it wholesale
(`TechniqueOverlay.block_bodies`). Measured consequence: a rewrite that adds a
correct new rule also drops the working general instructions, so training-split
gains do not survive on held-out data.

Add an **append** mutation alongside the existing rewrite: keep the current
block text and add one rule addressing the observed failure. Let the search try
both and let the measurement decide.

**Acceptance:** a new test proves an append candidate preserves the original
text; a real run on `entity-extraction-hard` with `qwen2.5:7b` shows the
held-out delta is no longer negative. Record the result in
`docs/benchmarks/native-vs-mipro.md` **including if it fails** — a negative
result is a finding, not a reason to hide it.

---

## Task 3 — upload your own dataset from the web interface

`data/static/index.html` only offers bundled datasets from a dropdown; a user's
own data requires the CLI (`--dataset-file`).

Add an upload path: a `POST /v1/datasets/upload` endpoint that validates JSONL
against `BenchmarkExample`, reports the line number of the first bad row, and
makes the dataset selectable for benchmark/compare/optimize in the session.

**Acceptance:** a malformed file produces a readable error naming the line;
a valid file can be benchmarked from the UI without touching the terminal;
API tests cover both.

---

## Task 4 — widen the sandbox where it is measurably too narrow

`sandbox.py` allows no imports, which forced 9% of MBPP tasks to be dropped on
import (`integrations/huggingface.py:code_example`). Those tasks were discarded
because grading them would measure the sandbox, not the prompt.

Add a small module whitelist exposing pure functions only — `math`, and the
pure parts of `itertools` and `collections` (`Counter`, `defaultdict`). Bind
them as pre-populated names rather than implementing `import`, so no attribute
traversal is introduced.

**Acceptance:** the escape tests in `tests/test_graders.py` still all fail to
escape; the share of MBPP reference solutions passing rises above the current
91%; the drop filter is relaxed to match.

---

## Task 5 — measure on a second class of model

Every measurement so far is from two local models. `MeasurementStore.lookup`
deliberately requires an exact model match, so nothing transfers.

Run the existing comparisons against one OpenAI-compatible endpoint
(`--provider openai --base-url ...`) on `entity-extraction-hard` and `gsm8k`,
and record whether the ordering of techniques holds. **Do not commit API keys**;
read them from the environment.

**Acceptance:** `docs/benchmarks/` gains a note stating whether the
reading-versus-computation split reproduces on a larger model, with the numbers.

---

## Order and judgement

Do them in the order above; Task 1 unblocks the most. Each task should land as
its own commit with tests, lint clean, and the registry lint clean.

If you find that something here is wrong — a gap that does not exist, an
acceptance criterion that cannot be met honestly — say so and explain, rather
than producing something that technically passes. Several findings in this
project came from a test catching a claim that was not true; that is the
standard to hold.
