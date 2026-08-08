# Summarization dataset

`summarization.jsonl` contains 120 short operational reports. Three are
hand-written and the rest are generated deterministically from controlled
project, location, date, percentage, and participant fields.

## Annotation rules

- The five required facts are verbatim spans in the document.
- `contains_all` gives partial credit for preserved facts.
- `length_limit` requires at most 170 output characters.
- The compact expected string is an audit aid; it is not treated as the only
  valid summary.

Rebuild with `python scripts/build_uncovered_datasets.py` (seed `20260808`).

## Baseline

Measured on 2026-08-08 with `qwen2.5:7b`, one repeat over all 120 examples,
using `direct.explicit-constraints` and no structured-output mode:

| grader | score |
|---|---:|
| `contains_all` (headline quality) | 0.922 |
| `length_limit` | 0.800 |

Reliability was 0.800 and there were no provider failures. Both correctness and
constraint compliance therefore retain measurable headroom.

```bash
prompt-selector benchmark --model qwen2.5:7b --model-class medium \
  --dataset summarization --task summarization \
  --technique direct.explicit-constraints --capabilities system_messages \
  --no-strict-json
```
