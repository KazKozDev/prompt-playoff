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
