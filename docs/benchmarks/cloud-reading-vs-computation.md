# Reading versus computation on an OpenAI-compatible cloud model

Measured on 2026-08-08 against the OpenAI-compatible DeepSeek endpoint with
`deepseek-v4-pro` (`model_class=large`). The API key came from the environment;
no credential or token was written to the repository.

## Result: the full split did not reproduce

The reading-side ordering reproduced directionally: on 40
`entity-extraction-hard` examples, the direct schema-first technique beat
zero-shot chain of thought. The computation-side ordering did not reproduce: on
20 GSM8K examples, both techniques reached the ceiling.

| Dataset | Technique | Quality | Exact match | Reliability | Mean seconds | Mean tokens | Calls |
|---|---|---:|---:|---:|---:|---:|---:|
| `entity-extraction-hard` | `structured.schema-first` | **0.8875** field F1 | **0.675** | 1.000 | 4.4782 | 470.4 | 1.0 |
| `entity-extraction-hard` | `reasoning.zero-shot-cot` | 0.8592 field F1 | 0.575 | 1.000 | 19.7043 | 1,378.1 | 2.0 |
| `gsm8k` | `direct.explicit-constraints` | **1.0000** numeric accuracy | — | 1.000 | 4.7362 | 470.5 | 1.0 |
| `gsm8k` | `reasoning.zero-shot-cot` | **1.0000** numeric accuracy | — | 1.000 | 10.6086 | 1,033.6 | 2.0 |

There were zero provider failures in all 120 example-runs. JSON validity and
schema grading were 1.000 for every arm.

On extraction, adding a separate reasoning stage moved field F1 by **-0.0283**
and exact match by **-0.100**, while using 2.9 times the tokens and 4.4 times the
latency. The quality direction matches the local-model finding, but a 0.028 F1
gap on 40 examples is below the roughly 0.04 noise threshold used in the earlier
report, so this is directional replication rather than strong evidence of a
stable effect size.

On GSM8K, the earlier local result was 0.250 direct versus 0.850 zero-shot CoT.
Here both scored 1.000. This is a ceiling result, not evidence that reasoning
hurts computation: the larger cloud model solved every selected problem without
the extra stage. Chain of thought bought no measured accuracy and cost 2.2 times
the tokens and 2.2 times the latency. Therefore the claimed two-sided
reading-versus-computation split **does not reproduce on this model and sample**.

## Setup and limitations

- Extraction uses the documented 40-example slice, every fifth row of the
  200-row dataset: `rows[::5][:40]`.
- GSM8K uses the first 20 rows. The repository retained the earlier 0.250/0.850
  headline but no report artifact identifying its exact sample, so this run does
  not claim row-for-row replication of that older measurement.
- The endpoint rejects native `response_format.type=json_schema`. The runs used
  `--capabilities system_messages`, which embeds the same schema in the prompt;
  local JSON Schema graders still enforced the contract.
- An initial attempt against `https://api.openai.com` was excluded because the
  account returned `credit_balance_exhausted` before any model call. The DeepSeek
  run is the requested OpenAI-compatible endpoint measurement, not an OpenAI
  model measurement.
- One repeat measures ordering, not run-to-run stability. Reliability is 1.000
  here because every response passed its contract and no provider call failed.

## Reproducing

The provider reads `OPENAI_API_KEY` from the process environment. For this
endpoint, map the endpoint-specific environment variable only for the child
process:

```bash
OPENAI_API_KEY="$DEEPSEEK_API_KEY" prompt-playoff compare \
  --model deepseek-v4-pro --model-class large --provider openai \
  --base-url https://api.deepseek.com --capabilities system_messages \
  --dataset-file /tmp/prompt-playoff-task5/entity-40.jsonl \
  --task structured_extraction \
  --techniques structured.schema-first,reasoning.zero-shot-cot \
  --quality 1 --reliability 0 --latency 0 --token-cost 0

OPENAI_API_KEY="$DEEPSEEK_API_KEY" prompt-playoff compare \
  --model deepseek-v4-pro --model-class large --provider openai \
  --base-url https://api.deepseek.com --capabilities system_messages \
  --dataset-file /tmp/prompt-playoff-task5/gsm-20.jsonl --task coding \
  --techniques direct.explicit-constraints,reasoning.zero-shot-cot \
  --quality 1 --reliability 0 --latency 0 --token-cost 0
```
