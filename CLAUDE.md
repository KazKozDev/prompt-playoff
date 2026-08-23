# Prompt Playoff — working rules

## What this tool is

Prompt optimization and evaluation for **local** models. It picks the prompting
technique a task needs, compiles the prompt that implies, measures it on the
user's own model, and searches for a better one. Everything runs on the user's
machine; the runtime dependencies are `httpx`, `pydantic` and `pyyaml`, and that
is a promise, not an accident. Do not add a dependency to the core package
without saying why the three cannot do it.

## A screen is a thing you can look at; a mode is a way of looking at it

The rail carries five sections and thirteen destinations. That is the budget.

- **A new destination appears only in place of a deleted one.** Every good idea
  used to get its own screen, which is how the app reached twenty of them and
  stopped being able to keep its own navigation consistent with itself.
- **A screen must hold state or produce an artifact.** One that only explains
  something is documentation, and belongs in a guide.
- **Modes are for one thing seen differently**, not for two things sharing a
  tab. `results` (history / significance / regression gate) is one thing: the
  recorded runs. The old `release-center` (versions / regressions) was two, and
  that is precisely where the navigation drifted apart.
- **Every screen name is written once**, in `screenMeta` in `navigation.js`. The
  rail, the context bar and the browser title all read from it.
- **Renaming a route never breaks an old one.** `routeAliases` maps the old head
  to the new destination and `legacyMode` maps it to the mode; a path that split
  in two — `#release-center/versions` and `#release-center/regressions` went to
  different screens — goes in `legacyPaths`, which is consulted first.

## The gate is the committed file, not a click

`prompt-playoff.yaml` holds the thresholds, and `prompt-playoff check` enforces
them in CI. The UI's job is to **produce** that file, not to re-implement it.

- A single-user app must never ask its user to approve their own work. Registering
  a release used to raise a review item asking the same person to approve what
  they had just registered; one user cannot be two, and the click established
  nothing. Reviews holds only decisions a *model* asked a *person* to make:
  generated dataset rows, judge verdicts, breached gates.
- A register kept inside this app is not a system of record. Releases export a
  manifest and a `checks:` block; git and CI are the record.

## Numbers in prose are asserted, never typed

`tests/test_doc_numbers.py` compares every count the README and the guides state
out loud against the registry and `business_cases.yaml`. The guides once claimed
"50 jobs in ten categories" over a shelf of twelve categories and fifty-nine
tasks, and the README advertised thirty-two techniques over a registry of
sixty-one. Both files rendered perfectly while lying. If you state a count, add
it to `CLAIMS`.

The same rule covers structure the tests can only see as text: assertions in
`tests/test_api.py` and `tests/test_business_catalog.py` read the JavaScript and
check that a merged screen left no second implementation behind.

## Before you finish

```bash
.venv/bin/python -m pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .
```

Commit messages end at the body — no `Co-Authored-By` trailer.
