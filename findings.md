# Findings

## Existing capabilities
- The UI and API already support task description, model settings, technique recommendation, prompt authoring, benchmark, comparison, and optimization.
- Scorecards include quality, reliability, latency, token counts, and call counts, but not monetary cost.
- `prompt-playoff check` enforces committed thresholds and returns distinct pass/fail/configuration-error exit codes.
- Measurement evidence is persisted and reused by ranking; jobs are persisted separately.
- Prompt copying, technique YAML export, and promptfoo export exist, but promptfoo intentionally covers only the first stage.
- Tracing supports Langfuse and OTLP, but there is no experiment-history product surface or scheduled/alerting layer.

## Worktree safety
- The repository already contains modified and untracked user files, including API, service, UI, persistence, provider, and tests.
- All edits must be additive and must not revert or normalize unrelated changes.

## Product gaps to implement
- Saved secret-free model profiles and proactive connection verification.
- Provider price configuration and actual USD estimates.
- Versioned experiment snapshots and cross-version degradation comparison.
- Complete executable export for multi-call prompts.
- Webhook notifications for regression failures.
- UI controls and visual history for all of the above.

## Implemented backend contracts
- `ModelProfile` now accepts explicit input/output USD-per-million-token prices; absent prices remain unknown.
- Scorecards and individual runs carry nullable monetary cost without inventing provider tariffs.
- Saved model profiles are stored without request API keys and use atomic, process-safe JSON persistence.
- Connection checks verify Ollama model installation or an OpenAI-compatible authenticated model catalog without generation.
- Experiment history is append-only, stores aggregate scorecards and hashes instead of raw model output, and can compare two versions with direction-aware degradation flags.
- Runtime exports generate Python or TypeScript clients of `/v1/run`, preserving all multi-call strategies.
- Regression checks can deliver redacted outbound webhook notifications on failure or setup error.

## Production prompt audit: Support Desk v1

- `prompt-playoff.yaml` gates `structured.schema-first` on `entity-extraction`. The
  prompt actually in production, `Support Desk v1` (`direct.explicit-constraints`,
  `"You are a support agent. Answer in one paragraph."`), has no committed check —
  CI is green while the live prompt is unmeasured.
- A first attempt to add a check used `token_f1` against `business:support-reply`
  (60 rows) and scored 0.14. Manual inspection showed the low score is a grader
  artefact: `token_f1` is word-overlap, and the reference replies use fixed
  canned phrasing the model has no reason to repeat verbatim. Do not gate
  open-ended generation on `token_f1`; use pairwise LLM judging instead
  (`/v1/evaluate/pairwise`, judge must be a different model family from the one
  being measured — same family trips `self_preference_warning`).
- Pairwise judging (`qwen2.5:7b` as judge, 6 rows spread across the set) found a
  real defect, not a grader artefact: the prompt re-asks for the order number the
  customer already gave in their message. Reference answers won 6/6.
- `business:support-reply`'s `{{...}}` tokens (`{{Order Number}}`,
  `{{Online Company Portal Info}}`, `{{Customer Support Hours}}`, etc.) are
  mail-merge placeholders repeated verbatim across all 60 rows, not values the
  model or a human author needs to fill in. The reference answers are numbered
  self-service instructions built entirely from these placeholders.
- Root cause: the system prompt's `"Answer in one paragraph"` constraint
  structurally rules out the numbered self-service format the dataset expects,
  independent of the re-asking issue. A rewrite that keeps this constraint
  cannot fix the defect.
- Fix, validated by blind pairwise judging with `gpt-oss:20b` as judge (a
  stronger, different-family model; corrected rubric with no paragraph-count
  constraint): a rewritten system prompt that (a) tells the model to copy
  `{{...}}` placeholders verbatim rather than fill them in, (b) asks for a
  numbered self-service guide built from the same placeholder set, (c)
  forbids claiming to have looked up the order or inventing details not in the
  message. Won 4/4 completed comparisons (2 more errored on an app bug, see
  below), decisively (e.g. 0.40 vs 0.10, 0.45 vs 0.15).
  ```
  You are a support agent replying to a customer message. The message may contain
  merge-field placeholders like {{Order Number}} — copy them back verbatim, do not
  fill them in or invent real values for them.

  Give a numbered, step-by-step self-service guide the customer can follow (log in,
  find the order, take the action, confirm). Reference company specifics only as
  merge-field placeholders you introduce the same way: {{Online Company Portal Info}}
  for where they log in, {{Online Order Interaction}} for the button or link they
  click, {{Customer Support Hours}}, {{Customer Support Phone Number}}, and
  {{Website URL}} for how to reach a human if the steps do not work. Never claim to
  have looked up their order or invent details (dates, names) that were not in their
  message.
  ```
  Not yet applied to the production release — the rewrite is validated but the
  `Support Desk v1` release in Ship still carries the original text.
- App bug found along the way, now fixed: `POST /v1/evaluate/pairwise` returned
  a hard 502 when the judge emitted a score outside 0-10 (observed:
  `gpt-oss:20b` returning `20`, on a 0-100 scale). One particular input/answer
  pair hit this deterministically, so the retry after a 502 never helped. The
  reply is now read through `PairwiseJudgeReading`, which carries no upper
  bound, and `_judge_scale` maps 0-1 / 0-10 / 0-100 onto 0-1; the judge is also
  now told the scale in words, which the schema alone had not conveyed. The
  previously-failing pair now returns 200 (winner `a`, 1.0 vs 0.2), which
  supplied the sixth comparison the run above was missing.
- Second app bug found and fixed: both surfaces that print a dataset row — the
  library preview table (`platform.js`) and the report's example cards
  (`measurements.js`) — stringified the expected answer with `String(value)`,
  so every extraction set showed `[object Object]` under "Right answer". They
  now share one `asText` helper in `core.js` that renders objects as JSON.
- `checks.py`'s `CheckSpec.require` only accepts numeric `Scorecard` fields
  (code-graders); there is no committed-gate mechanism for pairwise-judge
  verdicts. A CI gate on judged quality would need new plumbing, not just a
  YAML entry.
