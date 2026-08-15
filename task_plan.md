# Productization implementation plan

## Goal
Complete the workflow from prompt evaluation to deployment and ongoing regression monitoring: saved model profiles with connection checks, monetary cost metrics, versioned experiment history, comparison charts, full Python/TypeScript exports, and regression notifications.

## Constraints
- Preserve all pre-existing user changes in the dirty worktree.
- Extend the current FastAPI, Pydantic, Typer, and single-file web UI architecture.
- Keep secrets out of persisted browser and server profile storage.
- Use deterministic calculations and tests; do not require live cloud providers.

## Phases
1. **Architecture and contracts** — complete
   - Map domain, scorecard, persistence, API, CLI, and UI extension points.
   - Define backwards-compatible schemas and storage boundaries.
2. **Backend foundations** — complete
   - Add model connection checking and secret-free saved profiles.
   - Add provider pricing and monetary scorecard fields.
   - Add versioned experiment records and comparison API.
3. **Exports and notifications** — complete
   - Export complete multi-stage Python and TypeScript runners/configuration.
   - Add regression notification webhook support and structured results.
4. **Product UI** — complete
   - Add profile management and connection check controls.
   - Add experiment history, version comparison, cost, and degradation charts.
   - Add export actions.
5. **CLI and documentation** — complete
   - Expose new workflows and document configuration/security behavior.
6. **Verification** — complete
   - Add/update tests, run formatting/lint/test suite, and exercise the UI/API path.

## Key decisions
- Persist profile metadata only; API keys remain request-scoped or environment-backed.
- Represent money in USD with explicit nullable values when pricing is unknown.
- Store append-only experiment snapshots separately from selector measurements.
- Notifications are outbound webhooks triggered by failed regression checks.

## Errors encountered
| Error | Attempt | Resolution |
|---|---:|---|
| Cost threshold discovery included the `grades` dictionary | 1 | Restricted discovery to scalar and nullable scalar numeric annotations; check tests pass. |
| Ruff reported formatting and long-line violations in new modules | 1 | Applied Ruff's safe fixes/formatter and wrapped generated-code strings manually. |
| Saved-profile form lost typed values while Ollama discovery completed | 1 | Stopped re-rendering the Settings panel; update only its hints and datalists in place. Browser retest saved the profile successfully. |

## Next step
Implementation and verification are complete; report the result and preserved worktree state.
