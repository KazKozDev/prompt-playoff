# Grounded QA research dataset

`grounded-qa.jsonl` now contains 120 source-grounded questions instead of the
original three-row smoke set. Two rows are hand-written and the rest are
constructed from controlled subjects, metrics, periods, values, and units.

## Annotation rules

- Settled cases require the subject, exact reporting period, value, and unit.
- Unsettled cases omit the requested period/metric combination and require the
  exact abstention token `INSUFFICIENT_EVIDENCE`; no adjacent-period value may
  be inferred.
- `grounding_overlap` measures whether answer words occur in supplied evidence.
- `contains_all` measures the construction-derived required facts or abstention.

Rebuild with `python scripts/build_uncovered_datasets.py` (seed `20260808`).

## Baseline

Measured on 2026-08-08 with `qwen2.5:7b`, one repeat over all 120 examples,
using `direct.explicit-constraints` and no structured-output mode:

| grader | score |
|---|---:|
| `grounding_overlap` (headline quality) | 0.721 |
| `contains_all` | 0.817 |

There were no provider failures. The separate `contains_all` score is important:
lexical grounding alone does not prove the requested value and period are right.

```bash
prompt-playoff benchmark --model qwen2.5:7b --model-class medium \
  --dataset grounded-qa --task research --technique direct.explicit-constraints \
  --capabilities system_messages --no-strict-json
```
