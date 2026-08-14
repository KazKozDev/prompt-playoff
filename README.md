# Prompt Playoff — Prompt Optimization and Benchmarking for Local LLMs

Prompt Playoff picks the prompting technique your task needs, compiles the prompt that technique implies, measures it on your own Ollama or OpenAI-compatible model, and searches for a better one. Chain-of-thought, self-consistency, ReAct, schema-first extraction and 25 more — ranked on your data, not on a blog post's opinion.

```bash
# macOS
git clone https://github.com/KazKozDev/prompt-playoff.git && cd prompt-playoff && ./start.command

# Windows
git clone https://github.com/KazKozDev/prompt-playoff.git && cd prompt-playoff && start.bat

# Linux — or any machine with Python 3.11+
pip install 'prompt-playoff[all]' && prompt-playoff serve
```

<p align="center">
  <a href="start.command"><img src="https://raw.githubusercontent.com/KazKozDev/prompt-playoff/main/assets/badges/macos.png" alt="macOS" height="36"></a>
  <a href="start.bat"><img src="https://raw.githubusercontent.com/KazKozDev/prompt-playoff/main/assets/badges/windows.png" alt="Windows" height="36"></a>
  <a href="#quick-start"><img src="https://raw.githubusercontent.com/KazKozDev/prompt-playoff/main/assets/badges/linux.png" alt="Linux" height="36"></a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/KazKozDev/prompt-playoff/main/assets/prompt-playoff-cli.gif" alt="Prompt Playoff benchmarking a prompt technique against a local Ollama model, then showing how it ranked the techniques" width="100%">
</p>

---

## Quick start

1. Run the commands above. The launchers prepare everything themselves — Python 3.11+, `.venv`, every optional extra, Ollama and `llama3.2:3b`, a free port, the browser.

2. Keep Ollama running with at least one local model. Selection and compilation work without one; only measurement needs it.

3. Describe the task, read the ranking, then measure the winner instead of trusting it:

   ```text
   describe → ranked techniques with reasons → compiled prompt → measured result → optimized prompt
   ```

   The same four steps are `recommend`, `compile`, `benchmark` and `optimize` on the command line.

## Prompt builder UI for local models

`prompt-playoff serve`, or either launcher, opens the same four steps in a browser.

<p align="center">
  <img src="https://raw.githubusercontent.com/KazKozDev/prompt-playoff/main/assets/prompt-playoff-ui.gif" alt="The Prompt Playoff web interface producing a schema-first prompt from a plain-language task, with the ranked alternatives below it" width="100%">
</p>

## Which prompting technique to use for your task

Selection runs in two passes. Hard constraints come first — declared capabilities, tool access, call budget, model class, and whether the evidence is supplied or still has to be fetched. Whatever survives is ranked on what the request looks like: dependent steps, a checkable answer, a fixed output shape, a long input, real cost of error. Not on its task type alone.

Every recommendation and every rejection carries its reasons, and says whether the number behind it was declared or measured:

```text
Schema-first output (structured.schema-first)
  • Strong declared fit for structured_extraction.
  • Built for this request being exact format, verifiable.
  • Unmeasured prior 0.91 from: task:structured_extraction, provider:ollama, default.
  • Executes as single (1 call minimum).
```

The registry ships **29 techniques** across 7 execution strategies — 13 `single`, 11 `multi_stage`, and one each of `self_consistency`, `map_reduce`, `tool_loop`, `program_of_thought` and `tree_search`. 22 of them carry the paper they come from, and the catalog links it.

Compilation then turns the task into the prompt *that technique implies* — its own blocks, stages and call count. Schema-first and map-reduce do not produce the same prompt with a different label on it:

```bash
prompt-playoff compile --task structured_extraction \
  --input-file examples/book_excerpt.txt --schema-file examples/entity_schema.json \
  --technique structured.schema-first --capabilities structured_output,system_messages
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

**quality** is the headline grader for that data — `field_f1` here, so 3 of 4 entities scores 0.86 rather than 0. **reliability** is contract pass rate × stability, because a technique that emits valid JSON every time but a different answer each time is not reliable. **stability** needs `--repeats > 1` and reports the share that produced the modal answer. Latency, tokens and calls are summed across every call the technique makes, so a three-sample technique reports three calls' worth of cost.

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

That contradicts the registry, which priors `structured.schema-first` at 0.95 for this task: on a 3B model the plainer technique wins. Results are recorded to `benchmark-results/measurements.json` and reused for later ranking, labelled `measured` instead of `prior only`.

Eleven datasets ship with the package, from a 6-example smoke set to `entity-extraction-hard`, `multiconer-en` and `few-nerd` at 200 each. `prompt-playoff list-datasets` prints their sizes and how many carry gold answers.

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

Only instruction blocks are mutable — a candidate cannot win by dropping the output contract. The Pareto front over quality, reliability, tokens and latency is reported next to the scalarized winner, so a cheaper-but-slightly-worse prompt stays visible instead of being averaged away.

`--backend` swaps the search algorithm and nothing else: the prompt is still built by this project's compiler, executed by the technique's own strategy and graded by its graders. `native` reflects on measured failures, `dspy:mipro` searches instructions and demonstrations jointly, `dspy:gepa` is reflective and Pareto-selected, `dspy:bootstrap` does demonstrations only and needs no proposer model.

```bash
prompt-playoff optimize --model llama3.2:3b --model-class small \
  --dataset entity-extraction --backend dspy:gepa --max-metric-calls 60
```

On `entity-extraction-hard` (40 examples, 26 train / 14 held out, `llama3.2:3b`), MIPROv2 beat the native loop by **+0.064 F1** over three repeats, using about half the model calls. Neither recovered the dataset's annotation rules, because the proposer was the same 3B model — [full write-up with the failure modes](docs/benchmarks/native-vs-mipro.md).

That last point is why the proposer is a separate profile. `PROMPT_PLAYOFF_ENGINE_MODEL` puts a stronger model on the job of writing candidate prompts while the numbers still describe your target model, and a run where the two are the same says so in its notes:

> Candidate prompts were written by llama3.2:3b, the same model the numbers describe. Part of the gain may be that model's own phrasing rather than a better prompt.

Selection, compilation and grading stay LLM-free either way: the engine never chooses the technique and never scores anything.

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
    require:
      quality_min: 0.85
      reliability_min: 0.95
      mean_total_tokens_max: 300
      p95_latency_seconds_max: 2.0
```

```bash
prompt-playoff check
```

Exit code `0` means every bound passed, `1` means at least one regression, `2` means invalid configuration such as an unknown dataset or an unreachable provider. Requirement names are explicit fields ending in `_min` or `_max`, and an empty `require` block is an error — a check can never pass while enforcing nothing. `--json` prints machine-readable output; `--update` rewrites the committed bounds to the current measurements, preserving YAML comments and key order.

For wider matrices, hand the work to promptfoo:

```bash
prompt-playoff export-promptfoo --techniques structured.schema-first,direct.explicit-constraints \
  --models llama3.2:3b,qwen3.5:4b --model-class small --dataset entity-extraction --output promptfoo
cd promptfoo && promptfoo eval && promptfoo view
```

The export writes the compiled prompts with `{{input}}` templated, a config covering techniques × providers, and a Python assertion bridge that calls **this project's graders** — so promptfoo reports the same `field_f1`, not a different metric wearing the same name. Multi-call techniques export their first stage only, and the command says so instead of silently truncating.

## Build datasets from traces and public corpora

```bash
prompt-playoff import-traces --output datasets/from-prod.jsonl --limit 200
prompt-playoff import-hf multiconer-en --output datasets/multiconer.jsonl --limit 200
```

With `PROMPT_PLAYOFF_TRACING` set to `langfuse` or `phoenix`, every call of every technique becomes its own span, and `import-traces` turns observed traffic into a dataset. Rows arrive with `expected: null` and tagged `unreviewed` — a trace has no gold answer, and pretending otherwise would benchmark a model against its own past mistakes.

Four presets convert Hugging Face corpora instead: [MultiCoNER v2](https://hf.co/datasets/MultiCoNER/multiconer_v2) and [Few-NERD](https://hf.co/datasets/DFKI-SLT/few-nerd) for extraction, [GSM8K](https://hf.co/datasets/openai/gsm8k) for reasoning graded on the number, and [MBPP](https://hf.co/datasets/google-research-datasets/mbpp) for code graded by running its own tests. Licence and citation are printed on every import.

## How it differs from DSPy, promptfoo and PromptWizard

**DSPy** optimizes the prompt inside a module you have already chosen — you write `dspy.ChainOfThought` or `dspy.ReAct` yourself. Prompt Playoff makes that choice for you, deterministically and with its reasons printed, then hands the winner to DSPy's search if you want it.

**promptfoo** measures prompts you have already written: a test harness, not a designer, and it does not tell you which technique the task needs. Prompt Playoff produces the prompt to be measured, and `export-promptfoo` hands it over.

**PromptWizard** and other agent-driven optimizers ask an LLM to critique and rewrite instructions. Prompt Playoff does that too, but only during optimization — never to choose the technique, never to score an answer.

### When not to use it

Do not use it for one prompt on one task that already works — selection needs something to rank against, and every number here comes from examples with expected answers. It pays for itself when several techniques are plausible, when you have a dataset with gold answers, when picking wrong is expensive, or when the choice has to be defended to somebody else.

It is also the wrong tool for open-ended prose: quality here is field overlap, grounding overlap, contract compliance and constraint coverage, not whether the writing is good.

## How it works

One Python package with a Typer CLI, a FastAPI service and a YAML registry.<br>
The **normalizer** turns a description into a `TaskProfile`.<br>
The **selector** filters on hard constraints, then ranks on the shape of the request, and prints a reason for every accept and reject.<br>
The **compiler** builds the blocks and stages that technique implies, and a strategy executor issues its 1..n provider calls.<br>
Deterministic **graders** score the result, and the measurement is stored where ranking, the optimizer and the CI gate all read it.

```text
Task → TaskProfile → Selector → Compiled prompt → Model calls → Graders → Measurement
```

One module per step, mapped in [docs/architecture.md](docs/architecture.md). Adding a technique is one YAML file and no Python — see [docs/extending.md](docs/extending.md).

```bash
prompt-playoff new-technique structured.my-technique
prompt-playoff validate-registry     # placeholders, strategies, graders, render probe
```

<details>
<summary>HTTP API</summary>

```text
GET   /v1/capabilities  /v1/techniques  /v1/datasets  /v1/lint  /v1/integrations
POST  /v1/recommend  /v1/select  /v1/compile  /v1/author  /v1/run
POST  /v1/benchmark  /v1/compare  /v1/optimize  /v1/export/promptfoo
GET   /v1/jobs  /v1/jobs/{id}  /v1/measurements
```

The reads mirror the CLI. Benchmark, compare and optimize return a job id immediately, because they issue real model calls; status, results, errors and the complete event stream are persisted atomically to `benchmark-results/jobs.json`, so the Logs view survives a restart.

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

Ollama plus eight OpenAI-compatible endpoints out of the box: `openai`, `anthropic`, `together`, `openrouter`, `groq`, `fireworks` and `deepseek`, each with its default base URL and its usual key variable (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, and so on). Unknown ids work too when given a `base_url`. Keys resolve from the Settings request key, then `model.api_key_env`, then the provider default, then `PROMPT_PLAYOFF_API_KEY`; a missing key fails before the request and names the variable to set.

Native JSON Schema is used when the model declares `structured_output`. Otherwise the schema is embedded in the prompt and validated after the call, and the compiler says so in its notes.

</details>

<details>
<summary>Requirements</summary>

Python 3.11 or newer, and — for anything that measures — Ollama with a local model such as `llama3.2:3b`, or an OpenAI-compatible endpoint.

**Optional extras**, installed only when needed: `[cli]` for the terminal commands, `[serve]` for the HTTP API and web UI, `[dspy]` for the MIPROv2/GEPA/Bootstrap backends, `[tracing]` for Langfuse or Phoenix, `[huggingface]` for the corpus presets, `[all]` for everything. The base install is the registry, selector, normalizer and compiler alone.

**macOS, Windows and Linux.** Linux has no launcher: install from PyPI and run `prompt-playoff serve`.

CI runs the suite on Linux across 3.11, 3.12 and 3.13, and on Windows on 3.12 — where it also starts the server and fails the build unless `/health` answers. The launchers themselves are not exercised there, so the double-click path is verified by hand rather than by CI.

</details>

<details>
<summary>Limitations</summary>

- Ranking still uses declared priors for any (technique, task, model) triple you have not benchmarked. The UI and the CLI mark those `prior only`.
- Of the 29 techniques, 6 carry `benchmarked` evidence, 16 `documented` and 7 `heuristic`. The label is on every row; do not read a prior as a measurement.
- `entity-extraction-hard` (200 examples) and `multiconer-en` (200, imported) are the datasets with real headroom. The others, especially the 6-example `entity-extraction`, are demonstrations.
- The optimizer is only as good as the model writing its proposals. With the target model doubling as the proposer, expect rephrasings rather than genuine rule discovery — use `--engine-model` to put a stronger model on that job.
- `tool_loop` executes only tools present in `prompt_playoff.tools`, which ships with a calculator. Register your own to benchmark real agent work.
- Graders are deterministic by design. There is no LLM judge, so open-ended generation cannot be scored on prose quality at all.
- The promptfoo export covers a technique's first stage only. Multi-call techniques must be measured here.
- Trace import reads from Langfuse only. Phoenix is write-only in this direction — spans go out, datasets do not come back.

</details>

<details>
<summary>Docker and development setup</summary>

```bash
docker build -t prompt-playoff .
docker run --rm -p 8000:8000 prompt-playoff
```

Open `http://127.0.0.1:8000`; the non-root image health-checks `/health`.

For a local checkout, `make test`, `make lint` and `make validate` are the gate — [CONTRIBUTING.md](CONTRIBUTING.md) has the setup and the exact commands CI runs. The suite replaces every provider call with controlled test doubles, so it needs no network and no running model server, and the optional extras are skipped when absent. `make validate` checks every technique file for unknown placeholders, strategies and graders, then render-probes the prompt it compiles to.

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
