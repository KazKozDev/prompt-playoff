# Prompt Playoff — Prompt Optimization and Benchmarking for Local LLMs

Prompt Playoff picks the prompting technique your task actually needs, compiles the prompt that technique implies, measures it on a real model, and searches for a better one — without asking an LLM which technique to use.

The selector is deterministic. It works as an offline **prompt optimization** tool, a local **LLM evaluation** harness, or a **prompt engineering** playground for Ollama and any OpenAI-compatible endpoint. Every score it prints is either a declared prior from the registry or a number measured on your model, and it always says which. Chain-of-thought, self-consistency, ReAct, schema-first extraction and 25 more techniques compete on your data instead of on a blog post's opinion.

<p align="center">
  <img src="https://raw.githubusercontent.com/KazKozDev/prompt-playoff/main/assets/prompt-playoff-demo.gif" alt="Prompt Playoff ranking prompt techniques and benchmarking them against a local Ollama model" width="100%">
</p>

<p align="center"><sub>Real run: task description → ranked techniques with reasons → compiled prompt → measured quality, reliability, latency and tokens.</sub></p>

```bash
# macOS
git clone https://github.com/KazKozDev/prompt-playoff.git
cd prompt-playoff
./start.command

# Linux — or any machine with Python 3.11+
pip install 'prompt-playoff[all]'
prompt-playoff serve
```

<p align="center">
  <a href="start.command"><img src="https://raw.githubusercontent.com/KazKozDev/book-translator/main/assets/badges/macos.png" alt="macOS" height="36"></a>
  <a href="#quick-start"><img src="https://raw.githubusercontent.com/KazKozDev/book-translator/main/assets/badges/linux.png" alt="Linux" height="36"></a>
</p>

<p align="center">Double-click <code>start.command</code> on macOS. Linux installs from PyPI and runs the same <code>serve</code> command.</p>

---

## Quick start

1. Run the commands above. On macOS, `start.command` finds a Python 3.11+ interpreter, builds `.venv`, installs the project with every optional extra, offers to install Ollama and pull `llama3.2:3b`, picks a free port in 8000–8020, and opens the browser. It rebuilds the environment when the checkout moved, because an editable install pinned to an old path imports fine and runs the wrong code.

2. Rank techniques for a task. This needs no model — selection is pure Python:

   ```bash
   prompt-playoff recommend "Extract entities from a book into strict JSON. Reliability matters most." \
     --model qwen3:14b --capabilities structured_output,system_messages
   ```

   ```text
                                              Recommended techniques
   ┏━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━┓
   ┃ Rank ┃ Technique                                ┃ Family                 ┃ Score ┃ Confidence ┃ Evidence ┃
   ┡━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━┩
   │    1 │ Schema-first output                      │ structured-output      │ 0.937 │      0.656 │ prior    │
   │    2 │ Label definitions with boundary examples │ classification-control │ 0.799 │      0.564 │ prior    │
   │    3 │ Few-shot schema with repair              │ few-shot               │ 0.765 │      0.642 │ prior    │
   └──────┴──────────────────────────────────────────┴────────────────────────┴───────┴────────────┴──────────┘
   ```

   Each row expands into its reasons, and the run ends with what it could not know:

   ```text
   Warning: No measured benchmark exists for this model yet; ranking uses declared priors. Run a
   benchmark on the compiled prompt to replace them with real numbers.
   ```

3. Keep Ollama running with at least one model, then measure the winner instead of trusting it. That command is the next section.

## Which prompting technique to use for your task

Selection runs in two passes. Hard constraints come first — declared capabilities, tool access, call budget, model class, and whether the evidence is supplied or still has to be fetched. Whatever survives is ranked on what the request looks like: dependent steps, a checkable answer, a fixed output shape, a long input, real cost of error. Not on its task type alone.

Every recommendation and every rejection carries its reasons:

```text
Schema-first output (structured.schema-first)
  • Strong declared fit for structured_extraction.
  • Built for this request being exact format, verifiable.
  • Priority fit (declared characteristics): quality 0.84, reliability 0.96, latency efficiency 0.92,
    token efficiency 0.90.
  • Designed for strict structured output.
  • Includes an explicit validation path.
  • Unmeasured prior 0.91 from: task:structured_extraction, provider:ollama, default.
  • Executes as single (1 call minimum).
```

The registry ships 29 techniques across 7 execution strategies:

| Strategy | Count | Techniques include |
|---|---|---|
| `single` | 13 | schema-first, explicit constraints, label rules, evidence-first, re-reading, contrastive CoT |
| `multi_stage` | 11 | few-shot + repair, critique + revise, plan + execute, decomposition, step-back, chain-of-verification, skeleton-of-thought |
| `self_consistency` | 1 | self-consistency sampling |
| `map_reduce` | 1 | long-context map-reduce |
| `tool_loop` | 1 | ReAct |
| `program_of_thought` | 1 | Program of Thoughts |
| `tree_search` | 1 | Tree of Thoughts (6 calls minimum) |

22 of the 29 carry the paper they come from, and the catalog links it. One adaptation was needed: the published forms emit reasoning and the answer in one response, which a schema-enforced call cannot do, so the reasoning gets its own stage and the answer stage carries the contract. That costs one extra model call, and the technique's `min_calls` says so.

Compilation turns the task into the prompt *that technique implies* — its own block structure, its own stages, its own call count. Schema-first and map-reduce do not produce the same prompt with a different label on it:

```bash
prompt-playoff compile --task structured_extraction \
  --input-file examples/book_excerpt.txt --schema-file examples/entity_schema.json \
  --technique structured.schema-first --capabilities structured_output,system_messages
```

```bash
prompt-playoff list-techniques
prompt-playoff show-technique structured.schema-first
```

## Benchmark and compare prompt techniques on your own model

`benchmark` runs the compiled prompt on a dataset and prints what the model actually did next to what the registry claimed:

```bash
prompt-playoff benchmark --model llama3.2:3b --model-class small --dataset entity-extraction --repeats 3
```

```text
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

- **quality** — the headline grader for the data. For extraction that is `field_f1`, so getting 3 of 4 entities scores 0.86 rather than 0.
- **reliability** — contract pass rate × stability. A technique that emits valid JSON every time but a different answer each time is not reliable.
- **stability** — with `--repeats > 1`, the share of repeats that produced the modal answer.
- **latency / tokens / calls** — summed across every call the technique makes. A three-sample technique reports three calls' worth of cost.

`compare` ranks several techniques on one dataset, weighted by your priorities:

```bash
prompt-playoff compare --model llama3.2:3b --model-class small --dataset entity-extraction \
  --techniques structured.schema-first,structured.few-shot-repair,reasoning.self-consistency,direct.explicit-constraints
```

```text
  Technique                       Weighted  Quality  Reliability  Latency s  Tokens  Calls
  direct.explicit-constraints        0.962    0.891        1.000       0.64     127    1.0
  structured.schema-first            0.833    0.867        1.000       1.11     204    1.0
  structured.few-shot-repair         0.711    0.700        1.000       1.51     366    2.0
  reasoning.self-consistency         0.706    0.775        1.000       2.08     499    3.0
```

That contradicts the registry, which priors `structured.schema-first` at 0.95 for this task. On a 3B model the plainer technique wins. Results are recorded to `benchmark-results/measurements.json` and reused for later ranking, labelled `measured` instead of `prior only`.

Eleven datasets ship with the package — `entity-extraction-hard`, `multiconer-en` and `few-nerd` at 200 examples each, `support-classification` at 150, `agents`, `gsm8k`, `grounded-qa`, `summarization` and `translation` at 120, `mbpp` at 80, and a 6-example `entity-extraction` smoke set. `prompt-playoff list-datasets` prints how many examples each one has and how many carry gold answers.

## Automatic prompt optimization, natively or with DSPy

```bash
prompt-playoff optimize --model llama3.2:3b --model-class small \
  --dataset entity-extraction --technique structured.schema-first \
  --rounds 3 --token-cost 0.3 --export my-technique.yaml
```

The loop: seed candidates (baseline, plus few-shot demos bootstrapped from the train examples the baseline already gets right) → benchmark each on the train split → score with your priorities over measured quality, reliability, latency and tokens → feed the worst failures back to the model and ask for better instructions → repeat → verify the winner on data it never optimized against.

```text
  Metric (held-out)   Baseline   Optimized     Delta
  quality                1.000       1.000    +0.000
  reliability            1.000       1.000    +0.000
  mean tokens          211.500     201.000   -10.500
  mean latency s         0.826       0.741    -0.086
```

Only instruction blocks are mutable — a candidate cannot win by dropping the output contract. The Pareto front over (quality, reliability, tokens, latency) is reported alongside the scalarized winner, so a cheaper-but-slightly-worse prompt stays visible instead of being averaged away.

`--backend` swaps the search algorithm without changing anything else. The prompt is still built by this project's compiler, executed by the technique's own strategy, and graded by its graders:

```bash
prompt-playoff optimize --model llama3.2:3b --model-class small \
  --dataset entity-extraction --backend dspy:gepa --max-metric-calls 60
```

| Backend | Searches |
|---|---|
| `native` | instructions, by reflecting on measured failures |
| `dspy:mipro` | instructions and demonstrations jointly (MIPROv2) |
| `dspy:gepa` | instructions, reflectively, Pareto-selected (GEPA) |
| `dspy:bootstrap` | demonstrations only — runs without a proposer model |

On `entity-extraction-hard` (40 examples, 26 train / 14 held out, `llama3.2:3b`), MIPROv2 beat the native loop by **+0.064 F1** verified over three repeats, using about half the model calls. Neither recovered the dataset's annotation rules, because the proposer was the same 3B model. Full write-up including the failure modes: [docs/benchmarks/native-vs-mipro.md](docs/benchmarks/native-vs-mipro.md).

That last point is the reason the engine model is separate. Three jobs may use an LLM *for the selector* — reading a free-text task description, authoring the task-specific prompt from a selected technique, and proposing rewrites during optimization:

```bash
export PROMPT_PLAYOFF_ENGINE_MODEL=qwen3.5:9b
prompt-playoff recommend "Render this contract into German, keeping terms consistent."
```

```text
Task profile read by: engine
  "task_type": "translation",
  "domain": "legal",

Warning: Keyword matching would have chosen summarization; the engine chose translation.
```

The keyword matcher takes the first list entry whose substring appears in your text and falls through to `summarization` when nothing matches — the sentence above contains none of its translation cues. The engine reads it instead, and the warning states which path ran, so a profile is never silently guessed. Description-parse failures fall back to keyword matching and say so; authoring failures return an explicit error rather than passing the compiler scaffold off as a model-written prompt.

Selection, scaffold compilation and grading stay LLM-free: the engine does not choose the technique and does not score anything. Every `OptimizationResult` carries `engine_model_id` and `engine_is_target`, and a run where the model wrote its own prompts says so in its notes:

> Candidate prompts were written by llama3.2:3b, the same model the numbers describe. Part of the gain may be that model's own phrasing rather than a better prompt.

## Prompt regression testing in CI

Commit `prompt-playoff.yaml` with the model and the thresholds your build promises:

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

```bash
prompt-playoff check
```

Exit code `0` means every bound passed, `1` means at least one regression, `2` means invalid configuration or setup such as an unknown dataset or an unreachable provider. `--json` gives machine-readable output, `--no-record` leaves the evidence store untouched, and `--update` rewrites the committed bounds to the current measurements while preserving YAML comments and key order. `--update` and `--json` are intentionally mutually exclusive.

Requirement names are explicit Scorecard fields ending in `_min` or `_max`; expression strings are not accepted. An empty `require` block is an error, so a check can never pass while enforcing nothing.

For wider matrices, hand the work to promptfoo:

```bash
prompt-playoff export-promptfoo \
  --techniques structured.schema-first,direct.explicit-constraints \
  --models llama3.2:3b,qwen3.5:4b --model-class small \
  --dataset entity-extraction --output promptfoo

cd promptfoo && promptfoo eval && promptfoo view
```

The export writes the compiled prompts with `{{input}}` templated, a `promptfooconfig.yaml` covering techniques × providers, and a Python assertion bridge that calls **this project's graders** — so promptfoo reports the same `field_f1`, not a different metric wearing the same name. Native schema enforcement is exported into the provider config for the same reason. Multi-call techniques export their first stage only, and the command says so instead of silently truncating.

## Build datasets from traces and public corpora

```bash
export PROMPT_PLAYOFF_TRACING=langfuse   # or phoenix
prompt-playoff tracing-status
prompt-playoff import-traces --output datasets/from-prod.jsonl --limit 200
```

Tracing wraps the provider, so every call of every technique becomes its own span with its own latency and token counts. Imported rows arrive with `expected: null` and tagged `unreviewed` — a trace has no gold answer, and pretending otherwise would benchmark a model against its own past mistakes. Needs `pip install -e '.[tracing]'`.

```bash
prompt-playoff list-hf-presets
prompt-playoff import-hf multiconer-en --output datasets/multiconer.jsonl --limit 200
```

Four presets convert Hugging Face corpora into benchmark examples: [MultiCoNER v2](https://hf.co/datasets/MultiCoNER/multiconer_v2) (SemEval-2023, complex and ambiguous entities) and [Few-NERD](https://hf.co/datasets/DFKI-SLT/few-nerd) for extraction, [GSM8K](https://hf.co/datasets/openai/gsm8k) for reasoning graded on the number, and [MBPP](https://hf.co/datasets/google-research-datasets/mbpp) for code graded by running its own tests. The NER conversions keep gold values verbatim in the input and a deliberate slice of empty cases so precision errors still show. Licence and citation are printed on every import. Needs `pip install -e '.[huggingface]'`.

## How it differs from DSPy, promptfoo and PromptWizard

**DSPy** optimizes the prompt inside a module you have already chosen: you write `dspy.ChainOfThought` or `dspy.ReAct` yourself, and the optimizer tunes that module's instructions and demonstrations. Prompt Playoff makes the choice you would otherwise make by hand, deterministically and with its reasons printed, and then hands the winner to DSPy if you want its search — `--backend dspy:mipro` and `dspy:gepa` run against this project's compiler and this project's graders.

**promptfoo** measures prompts you have already written. It is a test harness, not a designer, and it does not tell you which technique the task needs. Prompt Playoff produces the prompt to be measured; `export-promptfoo` then writes a promptfoo project whose assertions call this project's graders, so both tools report the same `field_f1` rather than two metrics sharing a name.

**PromptWizard** and other agent-driven optimizers ask an LLM to critique and rewrite instructions. Prompt Playoff does that too, but only during optimization: selection is scored constraints, grading is deterministic code, and no model is ever asked how good its own answer was.

### When not to use it

Do not use it for one prompt on one task that already works — selection needs something to rank against, and every number here comes from examples with expected answers. It pays for itself when several techniques are plausible, when you have a dataset with gold answers, when picking wrong is expensive, or when the choice has to be defended to somebody else.

It is also the wrong tool for open-ended prose. There is no LLM judge in this project, so quality is measured as field overlap, grounding overlap, contract compliance and constraint coverage — not as whether the writing is good.

## How it works

One Python package with a Typer CLI, a FastAPI service, and a YAML registry. A new technique is one YAML file and no Python — see [docs/extending.md](docs/extending.md).

```text
Task description
      ↓
Normalizer → TaskProfile (task type, shape, priorities, constraints)
      ↓
Selector: hard constraints → ranking on request shape → reasons per technique
      ↓
Compiler → blocks and stages the technique implies
      ↓
Strategy executor → 1..n provider calls (Ollama / OpenAI-compatible)
      ↓
Graders → quality, reliability, stability, latency, tokens
      ↓
Measurements store → ranking evidence · Optimizer fitness · CI bounds
```

```bash
prompt-playoff new-technique structured.my-technique
prompt-playoff validate-registry     # placeholders, strategies, graders, render probe
prompt-playoff capabilities          # everything a YAML file may reference
```

<details>
<summary>Technical architecture</summary>

### Important files

- `start.command` — macOS launcher: interpreter discovery, environment rebuild, extras, Ollama, free port, browser.
- `src/prompt_playoff/normalizer.py` — free-text description → `TaskProfile`, with the keyword fallback.
- `src/prompt_playoff/selector.py` (466 lines) — hard constraints, ranking, and the reason for every accept and reject.
- `src/prompt_playoff/compiler.py` (192 lines) — technique spec → prompt blocks and stages.
- `src/prompt_playoff/strategies.py` (764 lines) — the seven execution strategies and their call sequencing.
- `src/prompt_playoff/graders.py` (580 lines) — 21 deterministic graders: `field_f1`, `exact_match`, `json_schema`, `grounding_overlap`, `label_accuracy`, `unit_tests`, `tool_success` and the rest.
- `src/prompt_playoff/optimizer.py` (968 lines) — native search loop, Pareto front, held-out verification, technique export.
- `src/prompt_playoff/engine.py` (1116 lines) — the optional engine model, its cache, and its fail-closed authoring path.
- `src/prompt_playoff/api.py` — the HTTP surface and the job queue behind it.

### HTTP API

```text
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

Benchmark, compare and optimize return a job id immediately, because they issue real model calls. Job status, results, errors and the complete event stream are persisted atomically to `benchmark-results/jobs.json`, so the Logs view survives a restart.

</details>

<details>
<summary>Configuration</summary>

| Variable | Default | What it changes |
|---|---|---|
| `PROMPT_PLAYOFF_ENGINE_MODEL` | Unset — keyword parsing only | Model that reads descriptions, authors prompts, and proposes rewrites |
| `PROMPT_PLAYOFF_ENGINE_PROVIDER` | Provider of the target model | Provider for the engine model |
| `PROMPT_PLAYOFF_ENGINE_BASE_URL` | Provider default | Base URL for the engine model |
| `PROMPT_PLAYOFF_ENGINE_CACHE` | `benchmark-results/engine-cache.json` | Engine answer cache, keyed by description, technique, scaffold, mode and engine model |
| `PROMPT_PLAYOFF_TRACING` | `none` | `langfuse`, `phoenix`, or none |
| `PROMPT_PLAYOFF_MEASUREMENTS` | `benchmark-results/measurements.json` | Evidence store read back into ranking |
| `PROMPT_PLAYOFF_JOBS_PATH` | `benchmark-results/jobs.json` | Persisted job records and event logs |
| `PROMPT_PLAYOFF_REGISTRY` | Packaged `data/` | Alternative technique, model and dataset root |
| `PROMPT_PLAYOFF_API_KEY` | Unset | Fallback API key for providers without their own variable |

`--engine-model`, `--engine-provider` and `--engine-base-url` override the environment per run, and the web UI has the same fields. The engine is a full profile of its own — a remote proposer against a local target is the point, so nothing is inherited from the model under test.

### Providers

Ollama and any OpenAI-compatible endpoint. Keys resolve in this order: an in-memory request key from Settings, `model.api_key_env`, the provider default below, then `PROMPT_PLAYOFF_API_KEY`. A missing key fails before the request and names the variable to set.

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

Unknown OpenAI-compatible provider ids require `base_url` and use `PROMPT_PLAYOFF_API_KEY` unless `api_key_env` names another variable. Anthropic uses `x-api-key` and `anthropic-version`; the other cloud providers use bearer auth. Native JSON Schema is used when the model declares `structured_output`; otherwise the schema is embedded in the prompt and validated after the call, and the compiler says so in its notes.

</details>

<details>
<summary>Requirements</summary>

- **Python 3.11 or newer**, as declared by `pyproject.toml`.
- **Ollama**, or an OpenAI-compatible endpoint, for anything that measures. Selection and compilation run without a model.
- **A local model** such as `llama3.2:3b`. The macOS launcher offers to pull it when Ollama has none.
- **Optional extras**, installed only when you need them:

| Install | For whom |
|---|---|
| `pip install prompt-playoff` | Python applications importing the registry, selector, normalizer and compiler |
| `pip install 'prompt-playoff[cli]'` | Terminal use — `recommend`, `benchmark`, `compare`, `optimize`, `check` |
| `pip install 'prompt-playoff[serve]'` | The HTTP API and web UI under Uvicorn |
| `pip install 'prompt-playoff[dspy]'` | MIPROv2, GEPA and BootstrapFewShot search backends |
| `pip install 'prompt-playoff[tracing]'` | Langfuse or Phoenix / OTLP |
| `pip install 'prompt-playoff[huggingface]'` | Corpus import presets |
| `pip install 'prompt-playoff[all]'` | Everything above |

`start.command` is a macOS launcher and depends on `open`, `lsof` and optionally Homebrew. Linux and Windows use the pip path; this checkout has not been verified through a clean-machine end-to-end run on those systems.

Docker: `docker build -t prompt-playoff .`, then `docker run --rm -p 8000:8000 prompt-playoff`. Open `http://127.0.0.1:8000`; the non-root image health-checks `/health`.

</details>

<details>
<summary>Limitations</summary>

- Ranking still uses declared priors for any (technique, task, model) triple you have not benchmarked. The UI and the CLI mark those `prior only`.
- Of the 29 techniques, 6 carry `benchmarked` evidence, 16 `documented` and 7 `heuristic`. The label is on every row; do not read a prior as a measurement.
- `entity-extraction-hard` (200 examples) and `multiconer-en` (200, imported) are the datasets with real headroom. The others, especially the 6-example `entity-extraction`, are demonstrations.
- The optimizer is only as good as the model writing its proposals. With the target model doubling as the proposer, expect rephrasings rather than genuine rule discovery — use `--engine-model` to put a stronger model on that job.
- `tool_loop` executes only tools present in `prompt_playoff.tools`, which ships with a calculator. Register your own to benchmark real agent work.
- Graders are deterministic by design. There is no LLM judge, so open-ended generation is measured on grounding overlap and constraint coverage rather than on prose quality.
- The promptfoo export covers a technique's first stage only. Multi-call techniques must be measured here.
- Trace import reads from Langfuse only. Phoenix is write-only in this direction — spans go out, datasets do not come back.

</details>

<details>
<summary>Development setup</summary>

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

```bash
make test          # pytest
make lint          # ruff
make validate      # registry lint
```

The suite replaces every provider call with controlled test doubles, so it needs no network and no running model server. Optional extras (`.[dspy]`, `.[tracing]`, `.[huggingface]`) are skipped when absent, so it also runs on a bare install. The current checkout:

```text
308 passed in 12.81s
```

`make validate` runs `prompt-playoff validate-registry --strict`, which checks every technique file for unknown placeholders, unknown strategies and unknown graders, then render-probes the prompt it compiles to.

</details>

## License

Prompt Playoff is free and open-source software licensed under the [MIT License](LICENSE).

<br><br>

<p align="center">
  <a href="https://pypi.org/project/prompt-playoff/"><img alt="PyPI" src="https://img.shields.io/pypi/v/prompt-playoff"></a>
  <a href="https://github.com/KazKozDev/prompt-playoff/blob/main/LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/License-MIT-blue.svg"></a>
  <a href="https://github.com/KazKozDev/prompt-playoff/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/KazKozDev/prompt-playoff/actions/workflows/ci.yml/badge.svg"></a>
  <a href="https://www.python.org/"><img alt="Python 3.11+" src="https://img.shields.io/badge/Python-3.11%2B-3776AB.svg?logo=python&amp;logoColor=white"></a>
  <a href="https://ollama.com/"><img alt="Ollama" src="https://img.shields.io/badge/Ollama-local-000000.svg"></a>
  <a href="https://docs.astral.sh/ruff/"><img alt="Ruff" src="https://img.shields.io/badge/Ruff-passing-D7FF64.svg"></a>
</p>

<p align="center">
  <a href="https://github.com/KazKozDev/prompt-playoff/issues">Issues</a> ·
  <a href="https://github.com/KazKozDev/prompt-playoff/blob/main/CONTRIBUTING.md">Contributing</a> ·
  <a href="docs/extending.md">Extending</a> ·
  <a href="docs/integrations.md">Integrations</a> ·
  <a href="references/README.md">Papers</a> ·
  <a href="https://github.com/KazKozDev/prompt-playoff/blob/main/LICENSE">LICENSE</a> ·
  <a href="https://www.linkedin.com/in/kazkozdev/">LinkedIn</a>
</p>
