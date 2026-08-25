# Configuration

Everything here is optional. The defaults run a local Ollama model with no
environment set at all.

## Requirements

- **Python 3.11 or newer**, as declared by `pyproject.toml`.
- **Ollama**, or an OpenAI-compatible endpoint, for anything that measures.
  Selection and compilation run without a model.
- **A local model** such as `llama3.2:3b`. Both launchers offer to pull it when
  Ollama has none.

Optional extras, installed only when needed: `[cli]` for the terminal commands,
`[serve]` for the HTTP API and web UI, `[dspy]` for the MIPROv2/GEPA/Bootstrap
backends, `[tracing]` for Langfuse or Phoenix, `[huggingface]` for the corpus
presets, `[all]` for everything. The base install is the registry, selector,
normalizer and compiler alone.

`start.command` needs `open`, `lsof` and optionally Homebrew; `start.bat` needs
the `py` launcher, PowerShell and optionally winget. They do the same work and
differ only in how they ask the operating system for it. Linux has no launcher:
install from PyPI and run `prompt-playoff serve`.

CI runs the suite on Linux across 3.11, 3.12 and 3.13, and on Windows on 3.12 —
where it also starts the server and fails the build unless `/health` answers.
The launchers themselves are not exercised there, so the double-click path is
verified by hand rather than by CI.

## Environment variables

| Variable | Default | What it changes |
|---|---|---|
| `PROMPT_PLAYOFF_ENGINE_MODEL` | Unset — keyword parsing only | Model that reads descriptions, authors prompts, and proposes rewrites |
| `PROMPT_PLAYOFF_ENGINE_PROVIDER` | Provider of the target model | Provider for the engine model |
| `PROMPT_PLAYOFF_ENGINE_BASE_URL` | Provider default | Base URL for the engine model |
| `PROMPT_PLAYOFF_ENGINE_CACHE` | `benchmark-results/engine-cache.json` | Engine answer cache, keyed by description, technique, scaffold, mode and engine model |
| `PROMPT_PLAYOFF_TRACING` | `none` | `langfuse`, `phoenix`, or none |
| `PROMPT_PLAYOFF_MEASUREMENTS` | `benchmark-results/measurements.json` | Evidence store read back into ranking |
| `PROMPT_PLAYOFF_JOBS_PATH` | `benchmark-results/jobs.json` | Persisted job records and event logs |
| `PROMPT_PLAYOFF_EXPERIMENTS_PATH` | `benchmark-results/experiments.json` | Versioned aggregate experiment history |
| `PROMPT_PLAYOFF_PROFILES_PATH` | `benchmark-results/model-profiles.json` | Saved model metadata; API keys are excluded |
| `PROMPT_PLAYOFF_REGISTRY` | Packaged `data/` | Alternative technique, model and dataset root |
| `PROMPT_PLAYOFF_TECHNIQUES` | `benchmark-results/techniques` | Saved optimization winners: resolvable by id, never ranked |
| `PROMPT_PLAYOFF_CHECKS` | `prompt-playoff.yaml` | Committed thresholds; also the bar a release must clear to be approved |
| `PROMPT_PLAYOFF_API_KEY` | Unset | Fallback API key for providers without their own variable |
| `PROMPT_PLAYOFF_WEBHOOK_URL` | Unset | Receives failed/error regression-check payloads |

`--engine-model`, `--engine-provider` and `--engine-base-url` override the
environment per run, and the web UI has the same fields. The engine is a full
profile of its own — a remote proposer against a local target is the point, so
nothing is inherited from the model under test.

## Providers

Ollama plus seven OpenAI-compatible endpoints out of the box: `openai`,
`anthropic`, `together`, `openrouter`, `groq`, `fireworks` and `deepseek`, each
with its default base URL and its usual key variable (`OPENAI_API_KEY`,
`ANTHROPIC_API_KEY`, and so on). Unknown ids work too when given a `base_url`.

Keys resolve from the Settings request key, then `model.api_key_env`, then the
provider default, then `PROMPT_PLAYOFF_API_KEY`; a missing key fails before the
request and names the variable to set.

Monetary cost is calculated only when both `input_cost_per_million_usd` and
`output_cost_per_million_usd` are set on the model profile. Prompt Playoff does
not ship a mutable tariff catalog: a missing reviewed price is reported as
unknown rather than zero.

## The check file, and what a bar can be written against

`prompt-playoff.yaml` holds the thresholds `prompt-playoff check` enforces in
CI. Each `require:` key names a measurement and the side of it that is bounded.

| Key | What it bounds |
|---|---|
| `<scorecard field>_min` / `_max` | A headline number: `quality`, `reliability`, `stability`, `contract_pass_rate`, `mean_latency_seconds`, `p95_latency_seconds`, `mean_total_tokens`, `mean_cost_usd`, and the rest of the card |
| `grade.<grader>_min` / `_max` | One named grader's mean — `grade.contains_all_min: 1.0`, `grade.forbidden_content_min: 1.0` |

`--update` rewrites the values of both kinds in place, keeping comments and
ordering.

### Open-ended generation

A task with one right answer is gated on `quality_min`, and `quality` is
whichever grader decided that answer. A drafted reply, summary or email has no
such grader: the run falls back to `token_f1`, which scores how many words the
answer shares with the single reference the row happens to hold. A good reply
worded differently scores around 0.14 there; only a copy of the reference
reaches 1.0. A `quality_min` over that would pin how closely the model echoes
one person's wording — something a better prompt can lose and a worse one can
keep — so `prompt-playoff check` **refuses** it and names what to write instead.

What it enforces is `grade.<grader>_min`, which turns a requirement no reference
answer exists for into a CI failure. Give the rows requirements a rule can
decide:

```json
{"id": "reply-1",
 "input": "Where is order A-4471?",
 "graders": ["contains_all", "forbidden_content", "length_limit"],
 "grader_options": {"contains": ["A-4471"],
                    "forbidden": ["refund", "guarantee"],
                    "forbidden_patterns": ["\\[INSERT [A-Z ]+\\]"],
                    "max_chars": 700}}
```

and bound them:

```yaml
require:
  grade.contains_all_min: 1.0        # every reply cites the order number
  grade.forbidden_content_min: 1.0   # none of them promises a refund
  grade.length_limit_min: 0.98       # they fit the channel
```

`grade.token_f1_min` is permitted and means what it says: watch word overlap for
drift between runs of the same prompt. It is not a bar on quality, and writing
it explicitly is how you record that you know the difference.

You do not have to write those requirements by hand. In the app they are one
button on **Datasets** — pick the shape of the work beside your set and press
**Add requirements**. From the terminal it is `prompt-playoff
annotate-dataset rows.jsonl --contract reply --in-place`, which derives them per row —
the identifier the reply has to carry back, the unfilled `[INSERT NAME]` that
must not ship, the length the channel allows — and keeps a check only where the
row's own reference answer already meets it, so nothing it writes can mark a
model wrong for answering as well as a person did. `--contract summary` requires
the facts the human summary kept; `--contract draft` does the format checks
alone. Run it without `--contract` and it only writes down the graders the tool
would otherwise have guessed, so the choice on record is yours.

### What still cannot be gated

Tone, persuasiveness, whether an explanation lands. **Evaluation → Answer
judging** (`POST /v1/evaluate/rubric`) judges a whole recorded run against the
reference answers its rows carry — blind, one review item for the batch — and
reports a win rate against the person who wrote them, where 0.5 means the prompt
writes about as well as they did. It deliberately has no route into a scorecard or a `require:`
key: a bar defended by a model's mood on the day is not a bar. What CI enforces
is what a rule decided.

### The prompt search refuses the same number

The prompt search stops before its first model call when the rows would
be scored by word overlap and that metric's floor is at or above 0.35 — the
point where it can no longer separate a good answer from an answer to a
different question. A search against such a number does not fail to improve the
prompt; it reliably raises the score by drifting towards the wording every row
shares. The refusal names what to give the rows instead, and offers one way
past it — `--allow-noisy-objective` on the CLI, **Search anyway, and read it as
drift** in the app.

`prompt-playoff list-datasets` prints, for every set whose quality number would
come from word overlap, what that metric already scores when the answer was
written for a *different* row of the same set. Where that floor is high — 0.41
on the bundled marketing-email corpus — the metric cannot separate a good answer
from an unrelated one at all, and no prompt work will move it. That listing is
how you find out whether a set can be improved against before you try.

The bundled drafting sets carry their requirements already: a set that declares
a `contract` in the catalogue has, per row, the checks a rule can decide,
derived from the rows themselves and kept only where the human answer meets
them. `business:support-reply` is the clearest case — its word-overlap floor was
0.63, because every reference in it is a template — and it is now scored on
whether the reply carries the order reference back, which is the thing the work
actually requires.

Regression webhooks can also be committed in the check file:

```yaml
notifications:
  webhook_urls:
    - https://monitoring.example/hooks/prompt-playoff
```

They are sent only for failed thresholds or setup errors. Delivery failures are
reported in the structured check result without replacing the original exit
code. Run `prompt-playoff monitor --interval-seconds 300` for a foreground
scheduled monitor, or execute `prompt-playoff check --json` from an existing CI
or scheduler.

Native JSON Schema is used when the model declares `structured_output`.
Otherwise the schema is embedded in the prompt and validated after the call, and
the compiler says so in its notes.

## Docker

```bash
docker build -t prompt-playoff .
docker run --rm -p 8000:8000 prompt-playoff
```

Open `http://127.0.0.1:8000`; the non-root image health-checks `/health`.
