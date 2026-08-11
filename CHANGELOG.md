# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Nothing yet.

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

- Added `prompt-selector check`, committed YAML expectations, JSON output, snapshot updates,
  explicit exit codes, and a deterministic CI gate.
- Added provider-specific API key resolution and Anthropic authentication headers.
- Added process-safe, atomic persistence with surfaced corrupt-file recovery.
- Added a non-root web UI Docker image and trusted-publishing release workflow.

### Changed

- **Breaking install change:** the base package now contains only the importable core. Install
  `[cli]`, `[serve]`, or `[all]` for command-line, HTTP/UI, or all optional features.
- Cloud provider failures now identify the credential or endpoint configuration to fix.

[Unreleased]: https://github.com/KazKozDev/prompt-selector/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/KazKozDev/prompt-selector/releases/tag/v0.3.0
[0.2.0]: https://github.com/KazKozDev/prompt-selector/releases/tag/v0.2.0
