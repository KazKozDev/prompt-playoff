# Agents dataset

`agents.jsonl` contains 120 deterministic tool tasks split evenly between
arithmetic and word counting. Two are hand-written and the remainder are
generated with seed `20260808`.

## Annotation rules

- Arithmetic answers are computed from the generated expression and use the
  calculator tool's displayed numeric representation.
- Word-count answers follow the registered `word_count` tool's token rule.
- `tool_success` requires real, non-error observations in the execution trace.
- `exact_match` requires the final answer and nothing else.
- Run tool techniques with `--tools-allowed --capabilities
  tool_calling,system_messages --no-strict-json`.

Rebuild with `python scripts/build_uncovered_datasets.py`.

## Baseline

Measured on 2026-08-08 with `qwen2.5:7b`, one repeat over all 120 examples,
using the real `agents.react` tool loop:

| grader | score |
|---|---:|
| `exact_match` (headline quality) | 0.458 |
| `tool_success` | 1.000 |

Every tool call succeeded and there were no provider failures. The headroom is
output-contract discipline: the model often added prose despite the exact-only
instruction.

```bash
prompt-selector benchmark --model qwen2.5:7b --model-class medium \
  --dataset agents --task agents --technique agents.react \
  --capabilities tool_calling,system_messages --tools-allowed --no-strict-json
```
