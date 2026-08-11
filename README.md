# Prompt Selector

An explainable decision engine that maps:

> **task → constraints → model capabilities → prompt technique → compiled prompt → measured result → optimized prompt**

The selector is deterministic: it does not ask an LLM which technique to use.
Every score it reports is either a declared prior from the registry or a number
measured on your model, and it always says which.

## What it does

1. **Selects.** Filters techniques on hard constraints (capabilities, tool
   access, call budget, model class, and whether the evidence is supplied or has
   to be fetched), then ranks the rest on what the request actually looks like —
   whether it has dependent steps, a checkable answer, a fixed output shape, a
   long input, real cost of error — not on its task type alone. Every
   recommendation and every rejection comes with its reasons.
2. **Compiles.** Turns the task into the prompt *that technique implies* — its
   own block structure, its own stages, its own call count. Schema-first and
   map-reduce do not produce the same prompt with a different label on it.
3. **Measures.** Runs the compiled prompt against a real model on a dataset and
   computes quality, reliability, stability, latency, tokens and call count from
   the actual calls. Measurements feed back into ranking.
4. **Optimizes.** Searches for a better prompt using those measurements as the
   fitness function, verifies the winner on a held-out split, and exports it as
   a new technique.

## Quick start

Install only the surface you use:

| Install | For whom |
|---|---|
| `pip install prompt-selector` | Python applications importing the deterministic registry, selector, normalizer, and compiler. |
| `pip install 'prompt-selector[cli]'` | Developers running terminal commands such as `recommend`, `benchmark`, and `check`. |
| `pip install 'prompt-selector[serve]'` | Deployments starting the HTTP API/UI with Uvicorn. |
| `pip install 'prompt-selector[all]'` | Contributors who want CLI, server, tracing, corpus imports, and every optimizer backend. |

For local development, clone the repository and install the development environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

Rank techniques for a task:

```bash
prompt-selector recommend "Extract entities from a book into strict JSON. Reliability matters most." --model qwen3:14b --capabilities structured_output,system_messages
```

Read the prompt a technique compiles to:

```bash
prompt-selector compile --task structured_extraction --input-file examples/book_excerpt.txt --schema-file examples/entity_schema.json --technique structured.schema-first --capabilities structured_output,system_messages
```

Measure it against a real model:

```bash
prompt-selector benchmark --model llama3.2:3b --model-class small --dataset entity-extraction --repeats 3
```

Start the web interface at `http://127.0.0.1:8000`:

```bash
# The command needs both command-line and server extras; [all] includes both.
prompt-selector serve
```

## Measured, not assumed

`benchmark` prints what the model actually did, next to what the registry
claimed:

```
                Measured: Schema-first output on llama3.2:3b
  Metric                      Measured   Declared
  quality                        0.867      0.840
  reliability                    1.000      0.960
  contract pass rate             1.000          —
  stability across repeats       1.000          —
  mean latency (s)               0.936          —
  mean tokens                    204.3          —
```

Where the numbers come from:

- **quality** — the headline grader for the data. For extraction that is
  `field_f1`, so getting 3 of 4 entities scores 0.86 rather than 0.
- **reliability** — contract pass rate × stability. A technique that emits valid
  JSON every time but a different answer each time is not reliable.
- **stability** — with `--repeats > 1`, the share of repeats that produced the
  modal answer.
- **latency / tokens / calls** — summed across every call the technique makes.
  A three-sample technique reports three calls' worth of cost.

Comparisons rank on those measurements, weighted by your priorities:

```bash
prompt-selector compare --model llama3.2:3b --model-class small --dataset entity-extraction \
  --techniques structured.schema-first,structured.few-shot-repair,reasoning.self-consistency,direct.explicit-constraints
```

```
  Technique                       Weighted  Quality  Reliability  Latency s  Tokens  Calls
  direct.explicit-constraints        0.962    0.891        1.000       0.64     127    1.0
  structured.schema-first            0.833    0.867        1.000       1.11     204    1.0
  structured.few-shot-repair         0.711    0.700        1.000       1.51     366    2.0
  reasoning.self-consistency         0.706    0.775        1.000       2.08     499    3.0
```

That result contradicts the registry, which priors `structured.schema-first` at
0.95 for this task. On a 3B model the plainer technique wins. Measurements are
recorded to `benchmark-results/measurements.json` and used for subsequent
ranking, labelled `measured` instead of `prior only`.

## Optimizing a prompt

```bash
prompt-selector optimize --model llama3.2:3b --model-class small \
  --dataset entity-extraction --technique structured.schema-first \
  --rounds 3 --token-cost 0.3 --export my-technique.yaml
```

The loop: seed candidates (baseline, plus few-shot demos bootstrapped from the
train examples the baseline already gets right) → benchmark each on the train
split → score with your priorities over measured quality, reliability, latency
and tokens → feed the worst failures back to the model and ask for better
instructions → repeat → verify the winner on data it never optimized against.

```
  Metric (held-out)   Baseline   Optimized     Delta
  quality                1.000       1.000    +0.000
  reliability            1.000       1.000    +0.000
  mean tokens          211.500     201.000   -10.500
  mean latency s         0.826       0.741    -0.086
```

Only instruction blocks are mutable — a candidate cannot win by dropping the
output contract. The Pareto front over (quality, reliability, tokens, latency)
is reported alongside the scalarized winner, so a cheaper-but-slightly-worse
prompt stays visible instead of being averaged away.

### The engine model

Three jobs in this project can use an LLM *for the selector*: reading a free-text
task description, authoring the task-specific prompt from a selected technique,
and proposing prompt rewrites during optimization. Description parsing keeps its
documented deterministic fallback; prompt authoring is fail-closed and never
returns the compiler scaffold as if it were a model-written prompt.

```bash
export PROMPT_SELECTOR_ENGINE_MODEL=qwen3.5:9b
prompt-selector recommend "Render this contract into German, keeping terms consistent."
```

```
Task profile read by: engine
  "task_type": "translation",
  "domain": "legal",

Warning: Keyword matching would have chosen summarization; the engine chose translation.
```

The keyword matcher takes the first list entry whose substring appears in your
text, and falls through to `summarization` when nothing matches — the sentence
above contains none of its translation cues. The engine reads it instead, and
the warning states which path ran, so a profile is never silently guessed.

`--engine-model` (plus `--engine-provider` and `--engine-base-url`) overrides the
environment per run, and the web UI has the same field. The engine is a full
profile of its own: a remote proposer against a local target is the point, so
nothing is inherited from the model under test.

Engine answers are cached in `benchmark-results/engine-cache.json`, keyed by
description, technique, scaffold, mode, and engine model. Description-parse
failures fall back to keyword matching and say so. Authoring failures return an
explicit error: no deterministic substitution is shown as a ready prompt.
Selection, scaffold compilation and grading remain LLM-free: the engine does not
choose the technique or score anything.

On the optimizer side the split is what makes the result interpretable. Every
`OptimizationResult` carries `engine_model_id` and `engine_is_target`, and a run
where the model wrote its own prompts says so in its notes:

> Candidate prompts were written by llama3.2:3b, the same model the numbers
> describe. Part of the gain may be that model's own phrasing rather than a
> better prompt.

### Stronger search: DSPy

`--backend` swaps the search algorithm without changing anything else — the
prompt is still built by this project's compiler, executed by the technique's
own strategy, and graded by its graders:

```bash
prompt-selector optimize --model llama3.2:3b --model-class small \
  --dataset entity-extraction --backend dspy:gepa --max-metric-calls 60
```

| Backend | Searches |
|---|---|
| `native` | instructions, by reflecting on measured failures |
| `dspy:mipro` | instructions and demonstrations jointly (MIPROv2) |
| `dspy:gepa` | instructions, reflectively, Pareto-selected (GEPA) |
| `dspy:bootstrap` | demonstrations only — runs without a proposer model |

Needs `pip install -e '.[dspy]'`. See [docs/integrations.md](docs/integrations.md).

On `entity-extraction-hard` (40 examples, 26 train / 14 held out, `llama3.2:3b`),
MIPROv2 beat the native loop by **+0.064 F1** verified over three repeats, using
about half the model calls. Neither recovered the dataset's annotation rules,
because the proposer was the same 3B model. Full write-up, including the failure
modes:
[docs/benchmarks/native-vs-mipro.md](docs/benchmarks/native-vs-mipro.md).

## CI gates and the model matrix: promptfoo

### Use it in CI

Commit `prompt-selector.yaml` with the model and thresholds your build promises:

```yaml
version: 1
model:
  provider: ollama
  model_id: llama3.2:3b
  model_class: small
  capabilities: [structured_output, system_messages]
checks:
  - name: entities-schema-first
    technique: structured.schema-first
    task: structured_extraction
    dataset: entity-extraction
    repeats: 3
    strict_json: true
    require:
      quality_min: 0.85
      reliability_min: 0.95
      mean_total_tokens_max: 300
      p95_latency_seconds_max: 2.0
```

Run `prompt-selector check`; use `--json` for machine-readable output,
`--no-record` to keep the evidence store untouched, or `--update` to replace the
committed bounds with the current measurements while preserving YAML comments and
key order. Exit code `0` means every bound passed, `1` means at least one regression,
and `2` means invalid configuration or setup such as an unknown dataset or unreachable
provider. `--update` and `--json` are intentionally mutually exclusive.

Requirement names are explicit Scorecard fields ending in `_min` or `_max`; expression
strings are not accepted. An empty `require` block is an error, so a check can never pass
without enforcing anything.

### Larger matrices with promptfoo

```bash
prompt-selector export-promptfoo \
  --techniques structured.schema-first,direct.explicit-constraints \
  --models llama3.2:3b,qwen3.5:4b --model-class small \
  --dataset entity-extraction --output promptfoo

cd promptfoo && promptfoo eval && promptfoo view
```

The export writes the compiled prompts with `{{input}}` templated, a
`promptfooconfig.yaml` covering techniques × providers, and a Python assertion
bridge that calls **this project's graders** — so promptfoo reports the same
`field_f1`, not a different metric with the same name. Native schema
enforcement is exported into the provider config for the same reason.

Multi-call techniques export only their first stage; the command says so
explicitly rather than silently truncating.

## Tracing and datasets from production: Langfuse / Phoenix

```bash
export PROMPT_SELECTOR_TRACING=langfuse   # or phoenix
prompt-selector tracing-status
```

Tracing wraps the provider, so every call of every technique is a separate span
with its own latency and token counts. Then turn observed traffic into a
dataset:

```bash
prompt-selector import-traces --output datasets/from-prod.jsonl --limit 200
```

## Datasets from public corpora

```bash
prompt-selector list-hf-presets
prompt-selector import-hf multiconer-en --output datasets/multiconer.jsonl --limit 200
```

Four presets convert Hugging Face corpora into benchmark examples:
[MultiCoNER v2](https://hf.co/datasets/MultiCoNER/multiconer_v2) (SemEval-2023,
complex/ambiguous entities) and [Few-NERD](https://hf.co/datasets/DFKI-SLT/few-nerd)
for extraction, [GSM8K](https://hf.co/datasets/openai/gsm8k) for reasoning graded
on the number, and [MBPP](https://hf.co/datasets/google-research-datasets/mbpp)
for code graded by running its own tests. The NER conversions keep gold values
verbatim in the input and a deliberate slice of empty cases so precision errors
still show. Licence and citation are printed on every import. Needs
`pip install -e '.[huggingface]'`.

Imported rows arrive with `expected: null` and tagged `unreviewed` — a trace has
no gold answer, and pretending otherwise would benchmark a model against its own
past mistakes. Needs `pip install -e '.[tracing]'`.

## Techniques

22 techniques across 5 execution strategies:

| Strategy | Techniques |
|---|---|
| `single` | schema-first, direct, label-rules, evidence-first, glossary translation, creative lattice, re-reading, contrastive CoT |
| `multi_stage` | few-shot + repair, critique + revise, plan + execute, decomposition, tests-first, zero-shot CoT, step-back, rephrase-and-respond, System 2 attention, chain-of-verification, skeleton-of-thought |
| `self_consistency` | self-consistency sampling |
| `map_reduce` | long-context map-reduce |
| `tool_loop` | ReAct |

Eight of them come from [The Prompt Report](https://arxiv.org/abs/2406.06608),
whose taxonomy of 58 text-based techniques is the shortlist for what to add next
— see [references/README.md](references/README.md). One adaptation was needed:
the published forms emit reasoning and the answer in one response, which a
schema-enforced call cannot do, so the reasoning gets its own stage and the
answer stage carries the contract. That costs one extra model call and the
technique's `min_calls` says so.

```bash
prompt-selector list-techniques
prompt-selector show-technique structured.schema-first
```

## Adding your own

A new technique is one YAML file and no Python. See
[docs/extending.md](docs/extending.md) for the block format, the placeholder
vocabulary, execution strategies, graders and datasets.

```bash
prompt-selector new-technique structured.my-technique
prompt-selector validate-registry          # placeholders, strategies, graders, render probe
prompt-selector capabilities               # everything a YAML file may reference
```

## HTTP API

```
GET  /v1/capabilities        strategies, graders, aggregators, datasets
GET  /v1/lint                registry health
GET  /v1/techniques          full technique specs
GET  /v1/datasets            datasets and their shape
GET  /v1/datasets/{name}     the examples themselves
POST /v1/recommend           rank from a description; returns the profile it ranked against
POST /v1/select              rank from an explicit TaskProfile
POST /v1/compile             the compiled prompt, stage by stage
POST /v1/author              have an engine model author prompt text from that contract
POST /v1/run                 execute it, with the full call trace
POST /v1/benchmark           start a measurement job
POST /v1/compare             start a multi-technique measurement job
POST /v1/optimize            start an optimization job (native or dspy:* backend)
POST /v1/export/promptfoo    write a promptfoo project
GET  /v1/integrations        which optional integrations are installed and active
GET  /v1/jobs                list current and historical jobs with their event logs
GET  /v1/jobs/{id}           poll progress and collect the result
GET  /v1/measurements        recorded evidence used for ranking
```

Benchmark, compare and optimize return a job id immediately, because they issue
real model calls. Job status, results, errors, and the complete event stream are
persisted atomically to `benchmark-results/jobs.json`, so the Logs view survives
application restarts. Set `PROMPT_SELECTOR_JOBS_PATH` to use another location.

## Providers

Ollama and any OpenAI-compatible endpoint. Keys resolve in this order: an
in-memory request key from Settings, `model.api_key_env`, the provider default
below, then `PROMPT_SELECTOR_API_KEY`.
A missing key fails before the request and names the environment variable to set.

| Provider id | Default base URL | Default key environment |
|---|---|---|
| `ollama` | `http://127.0.0.1:11434` | none |
| `openai` | `https://api.openai.com` | `OPENAI_API_KEY` |
| `anthropic` | `https://api.anthropic.com` | `ANTHROPIC_API_KEY` |
| `together` | `https://api.together.xyz` | `TOGETHER_API_KEY` |
| `openrouter` | `https://openrouter.ai/api` | `OPENROUTER_API_KEY` |
| `groq` | `https://api.groq.com/openai` | `GROQ_API_KEY` |
| `fireworks` | `https://api.fireworks.ai/inference` | `FIREWORKS_API_KEY` |
| `deepseek` | `https://api.deepseek.com` | `DEEPSEEK_API_KEY` |

Unknown OpenAI-compatible provider ids require `base_url` and use
`PROMPT_SELECTOR_API_KEY` unless `api_key_env` names another variable. Anthropic uses
`x-api-key` and `anthropic-version`; the other cloud providers use bearer auth.
Native JSON Schema is used when the
model declares `structured_output`; otherwise the schema is embedded in the
prompt and validated after the call, and the compiler says so in its notes.

## Docker UI

Build with `docker build -t prompt-selector .`.
Run with `docker run --rm -p 8000:8000 prompt-selector`.
Open `http://127.0.0.1:8000`; the non-root image health-checks `/health`.

## Development

```bash
make test          # pytest
make lint          # ruff
make validate      # registry lint
```

Optional extras (`.[dspy]`, `.[tracing]`) are skipped by tests when absent, so
the suite runs on a bare install.

## Limits worth knowing

- Ranking still uses declared priors for any (technique, task, model) triple you
  have not benchmarked. The UI marks those `prior only`.
- `entity-extraction-hard` (200 examples) and `multiconer-en` (200, imported)
  are the datasets with real headroom; the others are small demonstrations.
- The optimizer is only as good as the model writing its proposals. With the
  target model doubling as the proposer, expect rephrasings rather than genuine
  rule discovery — use `--engine-model` to put a stronger model on that job.
- `tool_loop` executes only tools present in the registry
  (`prompt_selector.tools`), which ships with a calculator. Register your own to
  benchmark real agent work.
- Graders are deterministic by design. There is no LLM judge, so open-ended
  generation is measured on grounding overlap and constraint coverage rather
  than on prose quality.
- The promptfoo export covers a technique's first stage only; multi-call
  techniques must be measured here.
- Trace import reads from Langfuse only. Phoenix is write-only in this
  direction — spans go out, datasets do not come back.
