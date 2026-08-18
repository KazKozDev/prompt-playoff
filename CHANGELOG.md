# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- The business catalogue: 50 jobs businesses pay a model to do, in ten categories — email, customer
  support, meetings, document routing, invoices and receipts, legal and contracts, finance, privacy
  and compliance, HR and recruiting, marketing and e-commerce — each mapped to the public dataset
  closest to its input → output shape. 17 cases get a
  direct match, 23 a near neighbour, and 10 are recorded as having no public set at all, because a
  benchmark that does not match the work is worse than no benchmark. The mapping lives in
  `data/business_cases.yaml`, is validated on load, and is served by `GET /v1/datasets/catalog`.
  Each case carries the company that reported it, what they pointed a model at, which vendor's
  customer story it comes from, and the figure they published where there is one — 4 hours to 1 on
  contract review, 8 weeks to 8 hours on product content, 8,000 hours a month on call summaries.
  Those figures are labelled claims and nothing here has checked one; a case is refused at load
  time if it has half a claim, a figure with nothing under it.
- 17 bundled datasets behind that mapping, named `business:*` and registered like any other set:
  email thread → reply, email → subject, subject → marketing email, transcript → minutes, live
  translation, support question → answer and → intent, retail and banking intent, invoice OCR →
  JSON fields, contract clause → type, clause → obligation, LegalBench reasoning, filing → figure,
  brief → product description, review → rating, résumé → fit. Each is a 50–60-row sample of a
  public Hugging Face repository, bundled so a first run needs no network, and each carries its
  source repository and licence in the UI. `scripts/fetch_business_datasets.py` re-downloads them.
- The Dataset library screen now has three zones: the catalogue of business cases, the business
  sets on this server with their sources and licences, and the task benchmarks and the sets you
  brought yourself — which stays the only zone where a set can be deleted. The catalogue is a shelf
  of ten tiles, each an illustration, the work it stands for in large type, and the verbs a person
  would search for if they did not know what the category was called; the count at its foot is
  counted from what this server can actually read, so a category described here with nothing
  bundled for it says so rather than borrowing a figure. It opens one
  category at a time into a card per case, built around the reported figure where there is one, with
  the match carried on the card's left edge as colour so a group reads at a glance and the dataset
  at its foot, one click from the rows. Opened on one set, the screen names the business cases that
  set stands for before it shows a row of it.
- `start.bat`, the Windows counterpart of `start.command`: it finds a Python 3.11+ through the
  `py` launcher, builds `.venv`, installs the extras and reports the ones that failed to build,
  starts Ollama and offers to install it with winget, takes a free port in 8000–8020, and opens
  the browser once `/health` answers. Windows is now in CI too — the suite on 3.12, plus a job
  that starts the server and fails the build unless `/health` answers.

### Changed

- Renamed the project from Prompt Selector to Prompt Playoff. Everything that carried the old
  name moves with it: the distribution is `prompt-playoff`, the import package is
  `prompt_playoff`, the CLI is `prompt-playoff`, the committed config is `prompt-playoff.yaml`,
  and the environment variables are `PROMPT_PLAYOFF_*` — `PROMPT_PLAYOFF_API_KEY`,
  `PROMPT_PLAYOFF_ENGINE_MODEL`, `PROMPT_PLAYOFF_TRACING`, `PROMPT_PLAYOFF_REGISTRY`,
  `PROMPT_PLAYOFF_JOBS_PATH`, `PROMPT_PLAYOFF_MEASUREMENTS`, `PROMPT_PLAYOFF_ENGINE_CACHE`,
  `PROMPT_PLAYOFF_ENGINE_PROVIDER`, `PROMPT_PLAYOFF_ENGINE_BASE_URL`, `PROMPT_PLAYOFF_INPUT`.
  The old names are not read as fallbacks: update imports, shell environments, config paths,
  and any `pip install prompt-selector` to the new spelling in one pass. `PromptSelectorService`
  keeps its name — it names the component, not the project.

## [0.3.0] - 2026-08-11

### Added

- Selection now reads the shape of a request, not only its task type. A task carries a `shape` —
  any of `multi_step`, `verifiable`, `underspecified`, `long_input`, `exact_format`,
  `has_examples`, `open_ended`, `high_stakes`, `computational` — and every technique declares the
  one to four it is built for in `suits`. Traits are weighted by how rare the claim is across the
  registry, and shape ranks *within* a task type rather than across it. The engine parse, keyword
  normalization and a `--shape` option on `select` and `compile` all supply it.
- Tasks declare whether the prompt carries the material to work on
  (`constraints.supplied_material`, read by the engine parse and by word count without one). A
  request that names a topic no longer gets a recipe built to quote, filter, re-read, chunk or
  translate an input it does not have — the failure was a finished prompt whose only honest answer
  was "the provided input does not contain this". Recipes can also word themselves for each case
  through the new `supplied_material` and `topic_only` block conditions, and a task type that works
  on something (summarization, translation, extraction) now says so when nothing was supplied.
- Tasks can declare `constraints.retrieval_required`: the material to answer from is not in the
  request and has to be fetched. Techniques declare `requires_supplied_evidence` when they answer
  only from pasted material; the two are a hard mismatch, and tool-using techniques gain a ranking
  bonus on such tasks. The engine parse, keyword normalization, `select` and `compile` all set it.

### Changed

- Five recipes no longer spend a second model call on a method their own paper runs in one prompt:
  `reasoning.chain-of-draft`, `grounding.chain-of-note`, `reasoning.metacognitive`,
  `reasoning.rephrase-and-respond` and `reasoning.self-ask` are single-call again, with the same
  phases as sections of one prompt. They had been written from a shared two-stage mould whose
  second call re-sent the whole input and added one instruction — for chain of draft that doubled
  the very cost the technique exists to cut. `validate-registry` now refuses a stage that reads
  nothing from the stage before it, and warns when a recipe claims to be cheap or fast while
  declaring more than one call.
- Ranking has usable spread. An extra model call is now priced by the work — dear on a request
  with no steps, cheap on one that has them — so a multi-stage recipe no longer wins a one-line
  request by a hundredth of a point. Two requests of the same task type get different techniques:
  a stepped, high-stakes coding task ranks plan-execute first, a checkable one with a fixed output
  ranks tests-first first.
- The authored-prompt view is one prompt per screen: stages read as numbered calls, labels are
  neutral, notes are a plain list instead of stacked warning banners, and the accent colour is
  reserved for the copy action.

### Fixed

- Prompts authored by the engine model no longer print the technique's block titles twice, with the
  task pasted under each. Authored sections now replace the matching scaffold section; only genuinely
  new text is appended as task-specific guidance.
- A later stage that came back as scaffold boilerplate is authored again, naming the stage: a
  multi-stage prompt no longer personalises its first call and leaves the rest generic.
- An authored answer is read out of whatever surrounds it, and in whatever shape the model chose.
  A fenced array behind a sentence, JSON after a block of reasoning, stage objects one after
  another, and an object keyed by stage name (`{"draft": {...}, "answer": {...}}`) all mean the
  same thing and are now accepted; the old greedy first-brace-to-last-brace match read a preamble
  as part of the document, or returned the first stage and dropped the rest, and the caller lost
  the whole prompt over punctuation.
- An engine model that echoes the compiled scaffold no longer costs the caller the whole prompt.
  Repeating the scaffold is a poor answer, not an unusable one — the stages, the placeholders and
  the method all survive it — so it is retried once and then kept, labelled
  `artifact_source: deterministic_compiler` with a note saying the engine added nothing. Authoring
  still fails closed when neither attempt returns the requested JSON or keeps the stage names and
  runtime placeholders, and that message now names the remedy.
- The authored-prompt cache key is stable across processes. It was built from a JSON dump whose
  set-valued fields ordered themselves by the process hash seed, so every restart missed the cache
  and re-ran the engine model for a request it had already answered.

## [0.2.0] - 2026-08-09

### Added

- Added `prompt-playoff check`, committed YAML expectations, JSON output, snapshot updates,
  explicit exit codes, and a deterministic CI gate.
- Added provider-specific API key resolution and Anthropic authentication headers.
- Added process-safe, atomic persistence with surfaced corrupt-file recovery.
- Added a non-root web UI Docker image and trusted-publishing release workflow.

### Changed

- **Breaking install change:** the base package now contains only the importable core. Install
  `[cli]`, `[serve]`, or `[all]` for command-line, HTTP/UI, or all optional features.
- Cloud provider failures now identify the credential or endpoint configuration to fix.

[Unreleased]: https://github.com/KazKozDev/prompt-playoff/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/KazKozDev/prompt-playoff/releases/tag/v0.3.0
[0.2.0]: https://github.com/KazKozDev/prompt-playoff/releases/tag/v0.2.0
