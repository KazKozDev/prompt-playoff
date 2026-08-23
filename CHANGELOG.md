# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `selector-eval`: the ranking is now graded, and the grade is a number. Every weight in the
  selector was set by hand in reaction to a case somebody noticed, and nothing in the project could
  say whether any of them helped. Wherever the measurement store holds two techniques benchmarked
  on the same task, model and dataset, that is a settled contest; the harness hides the cell, asks
  the ranking to place the entrants blind, and reports how much outcome following it costs against
  a coin flip. It spends no model calls. On the bundled measurements it read **lift +0.01** — the
  ranking was a coin flip with extra steps — which is what the entries below are answers to. Two of
  its first findings were about the data rather than the ranking: techniques were being compared
  across different datasets, and a model was being credited with fewer capabilities than the runs
  had already demonstrated it had, which ruled `agents.react` ineligible for an agents contest it
  had in fact won. CLI only for now; `--json` for the raw contests.
- Priors that measurement can reach (`prompt_playoff.priors`). `benchmark_priors: 0.84` in a
  technique file used to be the last word, unmovable by any number of benchmarks. It is now the
  starting point, shifted by what the runs found. Two things make that harder than averaging:
  scores from different datasets are not comparable, so nothing averages scores — every run becomes
  an *advantage* over the other techniques measured on exactly the same rows — and there is almost
  no data, so estimates are built coarse to fine and each level moves the one above it only as far
  as its own runs justify. Measured latency and tokens feed the efficiency axes the same way.
  Regret on the harness fell from **0.114 to 0.017**, lift from **+0.08 to +0.86**, worst single
  contest from **0.80 to 0.12**, and the result is flat across shrinkage constants from 2 to 16, so
  it is signal rather than a fitted number.

- Benchmarks record the request they answered, not only its task type. A score without the shape
  and constraints behind it is a number about a question nobody wrote down, and two of them cannot
  be compared: the same technique on the same rows, run once with tools and once without, produced
  two numbers, and the newer silently erased the older. `MeasuredEvidence.request` carries it,
  contests are keyed by it, and `selector-eval` says how many of its grades are replays and how
  many are reconstructions. Records made before this land under `unrecorded` and behave as they
  always did.

- The dataset library is browsed by the work, not by the file. `business_cases.yaml` carries a
  `taxonomy` beside its recorded cases: categories of business work, each listing the tasks under
  it, and every task is shown whether or not a packaged set measures it. The shelf used to be the
  sets it happened to have, so a task nothing measured was not a gap — it was invisible. A task
  routes to a business set or to one of the packaged benchmarks; anything else is a typo, and the
  loader now refuses the file instead of letting it degrade into a "No dataset" the screen states
  as though it were deliberate.
- **Do you need an LLM?** — a guide, in English and Russian, on the eight solution classes between a
  regular expression and a person, and the checks that decide which one a task needs. It is the
  question that comes before the prompt, and a tool that only ever answers "prompt" was not going to
  ask it. It is a mode inside Guides, not a fourteenth destination.
- `GET /v1/releases/{id}/manifest` freezes a release into two files a repository can hold: the whole
  provenance of the shipped prompt — exact text, fingerprint, the run that measured it, whether the
  two fingerprints agree, the rows it was measured on and whether they have moved since — and the
  same release expressed as the `checks:` block `prompt-playoff check` reads, so a project with no
  gate can acquire one by pasting rather than by learning the schema.

### Changed
- Registering a release no longer raises a review item. It asked the author to approve their own
  work, which is a click that establishes nothing: one user cannot be two, and the committed
  thresholds already decide the question. Reviews now holds only what a model asked a person to
  settle — generated rows, judge verdicts, breached gates. Files written by an older version keep
  their `release` rows; they are skipped on read rather than migrated, because rewriting a user's
  file to delete history is a heavier promise than ignoring rows nothing depends on.
- The rail's five sections have landing screens of their own — Prompt Studio, Evaluation,
  Production — and Model matrix and Context lab are two modes of one Test lab. They were one thing
  seen with one condition changed, filed as two destinations.
- The README said thirty-two techniques over a registry of sixty-one, and "25+ more" over
  fifty-seven. `tests/test_doc_numbers.py` now compares every count the prose states out loud
  against the registry and the catalogue, so a document can no longer render perfectly while lying.

- Prompt vs Fine-Tuning no longer paints a grey sheet behind the article. The
  page sits in a frame on a panel, and that grey `--bg` ignored the Light/Dark
  switch — so the guide stayed grey after the rest of the app had moved. Embed
  is now transparent, tokens follow the same light / dark / Auto rules as the
  app, and the switcher updates the frame instead of leaving it on the colour
  it loaded with. The screen plate no longer reprints the title above the
  article's own large heading, and the language chip sits in the hero instead
  of floating over it. Contents is its own plate on the page ground, the way
  every other split screen in the app sets a guide down beside the work. The
  guide now loads the same `docs.css` as Help: one token set, the app type
  ladder, and the same plate chrome. The large title and the two-zone layout
  stay; everything else is no longer a second copy of the theme. Inside the
  app, Contents is a viewport-tall rail beside the article — the frame is as
  tall as the document, so a sticky nav in there never stuck — and the current
  section is marked the way the sidebar marks the screen you are on. The
  standalone footer is hidden in the frame: it is not true, and it is not the
  app's voice. Help uses the same two-plate format: a contents rail beside an
  article with its own large title, no second heading from the screen chrome.

- `confidence` is a probability now, and one that can be checked. It was a blend of three numbers
  that between them estimated nothing — a technique showing 0.71 was no likelier to be right than
  one showing 0.58. It is now P(this technique beats the next one the ranking liked), from a spread
  that narrows as benchmarks accumulate. Read as a two-horse race deliberately: the probability of
  being best of sixty near-tied candidates is too small to print and too small to act on. On the
  bundled measurements it claims **67%** and those pairs go that way **68%** of the time, and
  `selector-eval` reports that gap every run.
- A low-confidence recommendation now names the techniques the ranking cannot separate instead of
  saying "run a task-specific benchmark" at nobody in particular.
- The task type of a description is the best-matching one, not the first one to match. The keyword
  fallback walked a literal list and stopped at the first hit, which made the order of that list
  into a decision: "summarize this python script" was read as coding. Every type is now scored, a
  word naming the work outranks any number of words naming the material, and `извлеч` gained the
  stem `извлек` — it never matched `извлеки`, which is the form the requests actually use.
- `Selector.rank` exposes the scoring without the family-diversity reshuffle `select` applies. The
  reshuffle is right for a person reading three suggestions and wrong for grading, because it hides
  whether the scoring put the right technique on top.

- A path out of the Optimization screen. The search winner used to be text on a page: `Releases`
  registered whatever was on `Prompt text`, which the search never touched, so a run could be
  optimized and shipped and the two would have nothing to do with each other. **Adopt optimized
  prompt** recompiles the winning instruction blocks against your own task and puts them on the
  prompt screen, marked `artifact_source: optimizer`. It recompiles rather than copies: the preview
  under the metrics was compiled against one row of the benchmark, so copying it would ship
  somebody else's example as your task. The button is not offered when the baseline won — adopting
  then would overwrite engine-written text with a plain compile of the recipe.
- `POST /v1/export/technique`: `optimize --export` over HTTP. Without `save` the technique YAML
  comes back for your own registry; with it, the server keeps the file and the id resolves — which
  is what lets `/v1/run` and an exported runtime client execute the winner instead of the recipe it
  was tuned from. Saved techniques are listed by `GET /v1/techniques` and removable with
  `DELETE /v1/techniques/{id}`, are never ranked by `/v1/recommend`, and may not take a registry
  recipe's name. They live in `PROMPT_PLAYOFF_TECHNIQUES`, one YAML each.
- Releases record the run that justified them. `experiment_id` existed on the record and nothing
  ever filled it, so a measured release and an unmeasured one looked alike; the register now shows
  which run each version was shipped on, and says `unmeasured` where there was none.
- Approving a release is gated on the thresholds in `prompt-playoff.yaml`, the same ones CI
  enforces — until now they guarded the repository and not the thing being shipped. The bar is
  applied to the run the release cites, with no new model calls. A bar that cannot be applied — no
  recorded run, or a run missing the field the bar names — refuses too: not knowing is not passing.
  A method the project set no bar for is gated by the person alone, as before. Readable ahead of
  the click via `GET /v1/releases/{id}/gate`.

- The search now rewrites your prompt, not the recipe behind it. Given the prompt you are holding,
  each candidate is a rewrite of its own messages rather than a patch to a registry block — which
  the block search could never reach, because by the time someone holds a prompt the blocks have
  been rendered into messages and an engine may have rewritten them. Two things are refused
  structurally: a rewrite that loses the place an example's input goes cannot be measured at all,
  and one already tried wastes the round. Everything else is settled by measurement. The winner is
  a prompt, so adopting it copies the measured text verbatim instead of recompiling, and no
  technique file is offered — a file of the untouched recipe would reproduce none of it.
- Releases verify the run they cite. A run records a fingerprint of the prompt it measured, and a
  release is marked `measured` only when that matches the text being frozen; `indirect` when a run
  is cited but measured something else — the optimization that produced the wording, say — and
  `unverified` when nothing is cited. Registering any of the three is allowed and recorded;
  approving on anything but `measured` is not.

- A release registered before its run existed is no longer stranded. `POST /v1/releases/{id}/cite`
  attaches a run after the fact, verified the same way as one supplied at registration — a run of a
  different prompt still lands as `indirect`, so this supplies evidence rather than skipping it. An
  approved release keeps the run it was approved on.
- A saved technique travels. The runtime export carries the technique file when it is one this
  server holds rather than one the package ships, and `POST /v1/techniques/import` takes it in at
  the other end. Before this the generated client only ran on the machine that made it.

- Worked examples for a prompt the search cannot find a place inside. A recipe renders
  demonstrations into a block it owns; finished text has no such block, and guessing a spot inside
  somebody's prose means deciding where their instructions end — which free text does not say. The
  demonstrations go beside the text instead: user/assistant turns immediately ahead of the real
  request, in the stage carrying the input, so the prompt underneath is untouched byte for byte.
  They are labelled on the prompt screen and one button takes them back out. The marker is internal;
  a provider is sent role and content and nothing else.

### Fixed

- Approving a release is refused when the examples have changed since the run it cites. The numbers
  described rows that no longer exist, and a bar cleared on them proves nothing about today's data.
- A comparison run records the fingerprint of the arm that was authored, so a release citing one is
  no longer marked as measuring a different prompt when it did not.
- The optimization screen claimed the search rewrites your words whichever backend was selected.
  Only the native one does; a DSPy backend searches the recipe's instruction block whatever it is
  measured against. The screen now says which, and the result carries the same note.
- `/v1/optimize` accepted a `prompt` and ignored it. The baseline was a fresh compile of the
  registry recipe while the screen beside it showed engine-written text, so a reported gain could
  be a gain over a prompt nobody had ever seen — and a loss against the one on the screen. The
  authored prompt is now the baseline in both the native and the DSPy backend, every result says
  which baseline it measured, and a prompt from another technique or with nowhere to put an
  example's input is refused before the run spends anything.

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

- The Evaluation guide is one document again, at `/evaluation` and `/evaluation/ru`. There were two:
  a `Benchmarks` page the app actually opened, dark-only with its own copy of the design tokens
  inside a `<style>` block, and the rewritten guide on the shared `/assets/docs.css` that no route
  served and nothing linked. The rewritten one is what ships; the old paths redirect to it, so a
  page cannot go stale by being the copy nobody edits. Its content now describes the workbench as it
  is: twenty-eight bundled sets in the library's three zones, the fifty-case business catalogue and
  the seventeen `business:*` sets behind it, `token_f1` and `injection_resistance` among the
  graders, the meaning/contract split drawn where `RELIABILITY_GRADERS` draws it, what a release
  needs before it can be approved, and what the search does to your own words. The Russian
  translation exists for the first time.
- Every screen and section now says, in plain words, what it is and what it is for. The one-liners
  were written as aphorisms — "Better or worse?", "Is the difference real?", "The gate between a
  prompt that scores well here and a prompt running in front of real users" — which read well and
  told a newcomer nothing about what the screen does. Significance now says it checks whether a
  difference is real or noise and what to paste in; Releases says it is a register of versions you
  freeze and roll back; Reviews says nothing in the queue proceeds until you answer. The home tiles
  and the status line under each section illustration were rewritten the same way, and the status
  line no longer repeats the panel description above it — it says what to do next from where you
  are.
- A pass over the screen copy for length. The guide beside every screen said each thing twice — once
  plainly and once as the reason it is that way — so each item is one or two sentences now and every
  number, threshold and formula stayed: the releases guide lost a third of its words without losing
  a rule. The section tiles no longer speak in another voice: "generate a high-performing prompt
  with automatic technique selection" and "all release pipelines are up to date" were describing a
  product rather than this one, which has no pipelines and deploys nothing. The upload screen
  stopped repeating its own checkbox, and the library stopped restating the panel header above it.
- The business categories are named in words that fit their tile: four of the ten headlines were
  being cut mid-phrase — "Automate support…", "Send documents to…" — because they were written
  longer than the two lines the shelf gives them.
- Both documents carry a contents strip, built by `/assets/docs.js` from their own headings rather
  than written out in four files that would drift from the pages under them. Twelve sections and
  ten thousand pixels is the problem the technique catalogue already solved with an index, and this
  is that idiom: a quiet kicker, the sections as links, the shape of the document before it is
  scrolled. Inside the app the frame is drawn at the document's full height, so it has nothing to
  scroll and a bare `#anchor` moved nothing — the jump is made on the page holding the frame, and
  it honours `prefers-reduced-motion` like the rest of the app.
- Help says what the workbench does now: twenty-eight bundled sets and the screen that generates
  rows, the catalogue of methods under Prompt rather than Reference, `Where it went wrong` by the
  name the measurement screen gives it, `token_f1` for prose, adopting an optimized prompt, and
  what a release has to prove before it can be approved. Russian was updated in the same pass.
- The document frame no longer pins `color-scheme:dark`: the page inside picks its scheme from the
  theme, and a light app was getting dark scrollbars and controls in the frame.
- A document opened inside the app is loaded with `?embed`, the switch both pages have carried
  since they moved to the shared stylesheet and nothing ever set: the panel header and the
  document's own title stopped saying the same words twice. The head keeps its language chip, which
  is the one thing the rail around it has no button for.

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
