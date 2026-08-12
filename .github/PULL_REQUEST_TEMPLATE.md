## What this changes

<!-- One paragraph. What behaviour is different afterwards, and why. -->

## Checks

```
ruff check .
ruff format --check .
pytest
prompt-playoff validate-registry --strict
```

- [ ] All four pass locally

## If this touches ranking or a technique

- [ ] Selector golden tests cover the new behaviour
- [ ] Any performance claim is backed by a measurement, or is labelled a
      declared prior — the two are reported differently and must not be mixed
- [ ] `min_calls` matches what the recipe actually spends

## If this touches the core

- [ ] Nothing the core imports reaches `fastapi`, `uvicorn`, `typer` or `rich`
      (the `core-only` CI job installs the package with no extras and asserts this)
