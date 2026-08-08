# Translation dataset

`translation.jsonl` contains 120 English-to-Spanish source/target pairs. Four
rows are hand-written; the remainder are deterministic combinations of actors,
actions, controlled terms, and cadences.

## Annotation rules

- Each source has a binding glossary with two source-to-target mappings.
- The source and target language live in `input`; the binding glossary lives in
  dataset `variables`, so a technique must actually render its glossary block.
- Every source glossary term occurs verbatim in the source and every required
  rendering occurs verbatim in the target.
- `glossary_consistency` measures required renderings; `omission_check` rejects
  outputs shorter than 0.55x or longer than 1.8x the source.
- The target is retained as audit evidence, but exact match is deliberately not
  used because valid translations need not have one surface form.

Rebuild with `python scripts/build_uncovered_datasets.py` (seed `20260808`).

## Baseline

Measured on 2026-08-08 with `qwen2.5:7b`, one repeat over all 120 examples,
using `direct.explicit-constraints` and no structured-output mode:

| grader | score |
|---|---:|
| `glossary_consistency` | 0.654 |
| `omission_check` | 1.000 |
| combined reliability | 0.827 |

There were no provider failures. The report's headline quality is 0.000 because
neither translation grader is classified as a unique-reference quality metric;
0.654 glossary consistency is the relevant headroom signal.

```bash
prompt-selector benchmark --model qwen2.5:7b --model-class medium \
  --dataset translation --task translation --technique direct.explicit-constraints \
  --capabilities system_messages --no-strict-json
```
