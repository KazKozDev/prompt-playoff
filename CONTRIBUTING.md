# Contributing

## Before opening a pull request

Run what CI runs. These four are the whole gate — if they pass locally, the
build passes:

```bash
ruff check .
ruff format --check .
pytest
prompt-playoff validate-registry --strict
```

`ruff format --check` only reports; `ruff format .` applies. `--strict` on the
registry lint fails on warnings too, which is what CI uses.

CI additionally installs the package with no extras and asserts the core still
imports without `fastapi`, `uvicorn`, `typer` or `rich`. Keep those imports out
of anything the core reaches, or that job fails while every test still passes.

## What a change should carry

1. Add or update one versioned technique recipe. A new technique is one YAML
   file and no Python — see [docs/extending.md](docs/extending.md).
2. Add selector golden tests for changed ranking behaviour.
3. Keep provider-specific logic inside an adapter.
4. Do not claim a technique is benchmarked without a reproducible dataset and
   grader configuration. A declared prior and a measured number are different
   things, and the output says which is which.

## Development environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

`[dev]` covers the CLI, the server and the test tools. The optional backends —
`[dspy]`, `[tracing]`, `[huggingface]` — are skipped by the suite when absent,
so a bare install runs green.
