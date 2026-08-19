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
