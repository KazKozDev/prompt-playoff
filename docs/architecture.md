# Architecture

## Pipeline

1. **Normalize** a form, JSON object, or short description into `TaskProfile`.
2. **Resolve capabilities** from the selected `ModelProfile`.
3. **Reject** techniques that violate hard constraints.
4. **Score** compatible candidates. Uses measured evidence where it exists and
   declared priors where it does not, and labels which.
5. **Diversify** the top results so the user sees materially different strategies.
6. **Compile** the chosen technique into a `CompiledProgram`: one
   `CompiledPrompt` per stage the technique's execution strategy will issue.
7. **Execute** through a strategy, which turns those stages into real provider
   calls and records the cost of each.
8. **Grade** the output with deterministic graders.
9. **Record** the measurement so step 4 stops guessing.
10. **Optimize** — optionally search for a better prompt with steps 6–9 as the
    fitness function.

## Why the selector is deterministic

An LLM can parse a user's description, but should not be the authority that
chooses a technique. A deterministic selector gives:

- reproducible recommendations;
- inspectable reasons;
- testable regressions;
- explicit compatibility failures;
- stable behavior when models are unavailable.

The optimizer *does* use an LLM — but only to propose candidate instructions.
Whether a candidate wins is decided by measurement, never by the model's opinion
of its own suggestion.

## Compilation

`PromptCompiler` never concatenates a generic template. It renders the
technique's own **blocks** — ordered, titled, individually conditional sections —
into one user message per stage.

```
TechniqueSpec.recipe.blocks   ─┐
TaskProfile + response_schema ─┼─> RenderContext ─> stage user message
CompileRequest.variables      ─┤
CompileRequest.exemplars      ─┘
```

Placeholders and conditions come from closed vocabularies (`templating.py`), so
a recipe can never execute code and a typo is a lint error rather than a literal
`{brace}` sent to a model.

Runtime placeholders (`{previous}`, `{chunk}`, `{partials}`) are deliberately
left unrendered at compile time. A compiled prompt therefore shows exactly where
execution-time data will land, and `CompiledPrompt.deferred_placeholders` lists
them.

## Execution strategies

A strategy owns the shape of the call sequence. Each declares a params model, so
`validate-registry` can check a technique's `execution.params` without running
anything.

| Strategy | Calls | Measured artefact |
|---|---|---|
| `single` | 1 | — |
| `multi_stage` | one per stage | stage outputs |
| `self_consistency` | `samples` | agreement ratio across samples |
| `map_reduce` | chunks + 1 | chunk count |
| `tool_loop` | up to `max_iterations` | tool calls and observations |

Every strategy returns an `ExecutionTrace` with one `CallRecord` per real call,
carrying latency and token counts. That is what makes multi-call techniques cost
what they actually cost in comparisons.

## Scoring

```text
score =
    0.30 × task_fit
  + 0.15 × model_fit
  + 0.35 × priority_fit
  + 0.15 × benchmark_signal
  + 0.05 × evidence_quality
  - complexity_penalty
  - call_penalty
```

`priority_fit` weights four axes by the user's normalized priorities. Those axes
are the technique's declared characteristics **until a measurement exists** for
that (technique, task, provider, model), at which point:

- `quality` and `reliability` come from the scorecard;
- `latency_efficiency` and `token_efficiency` are computed relative to the
  cheapest measured candidate in the same ranking;
- `benchmark_signal` becomes the measured quality/reliability blend weighted by
  what the task cares about, rather than a YAML prior;
- `evidence_quality` rises with the number of runs behind the measurement.

Priors remain declarable for `default`, `task:<task_type>`, `provider:<provider>`
and `class:<model_class>`, most-specific weighted highest. They are a cold-start
device, and the UI marks any recommendation resting on them as `prior only`.

## Measurement

`Scorecard` fields are all derived from real calls:

- `quality` — the highest-preference applicable grader (`field_f1` >
  `exact_match` > `label_accuracy` > …).
- `contract_pass_rate` — mean of the contract graders (`json_validity`,
  `json_schema`, `allowed_labels`, `tool_success`, …).
- `stability` — with repeats, the share of repeats producing the modal answer.
- `reliability` — `contract_pass_rate × stability`. Either failing sinks it.
- latency, tokens and calls — summed per example across every call.

Graders return `None` when inapplicable, so a dataset without `expected` still
yields contract metrics instead of a misleading zero.

`MeasurementStore` persists one record per (technique, task, provider, model,
dataset); newest wins. Lookup falls back from exact model, to provider, to task.

## Optimization

`PromptOptimizer` treats the compiler as the candidate generator and the
benchmark as the fitness function:

- **Seed** — baseline, plus a bootstrap candidate whose few-shot demos are the
  train examples the baseline already answers perfectly (cheapest first).
- **Propose** — the model is shown the current instruction block, its measured
  scorecard, and its worst concrete failures, then asked to rewrite under a
  stated bias (add a rule for the observed failure / cut tokens / reorder).
- **Select** — candidates are scored on measured numbers with the task's own
  priorities, costs normalized against the best candidate in the population.
- **Verify** — the winner is re-measured on a held-out split it never trained on.

Only instruction-bearing blocks are mutable (`MUTABLE_BLOCKS`); contract and
input blocks are off limits, so a candidate cannot score well by discarding the
output format. Results include the Pareto front over (quality, reliability,
tokens, latency), and the winner can be exported as a registry technique.

## Integration boundary

Three optional integrations plug in at three different seams, and each one is
deliberately given only the job it is better at:

| Integration | Seam | What it owns | What it never owns |
|---|---|---|---|
| DSPy | `PromptOptimizer` search | proposing candidates (MIPROv2, GEPA, Bootstrap) | building the prompt, scoring it |
| promptfoo | export | running the matrix, CI gating | the graders — they are exported as a Python assertion calling this project's own |
| Langfuse / Phoenix | `ModelProvider` wrapper | recording spans, storing production traffic | the benchmark; imported traces arrive without a gold answer |

The DSPy backend is the one worth being precise about. A `dspy.Predict` holds
the instruction text, but `forward` ignores DSPy's adapter and LM entirely: it
calls `PromptCompiler`, runs the technique's own strategy, and returns the real
output. The trace entry is appended manually, exactly as `dspy.Predict` does, so
demo bootstrapping still works. The metric is this project's graders collapsed
to one scalar by the task's priorities, plus a token penalty relative to the
baseline's measured prompt size. The winner comes back as a `TechniqueOverlay`,
which is the same object the native optimizer produces — so export, compile and
held-out verification are shared code.

Held-out verification never runs through DSPy's evaluator. It runs through
`BenchmarkRunner`, so the reported improvement is measured the same way every
other number in the project is.

## Provider boundary

`CompiledPrompt` is provider-neutral. Adapters translate it into:

- Ollama `/api/chat`, including `format` for JSON Schema and `think`;
- OpenAI-compatible `/v1/chat/completions`, including `response_format`.

`normalize_usage` maps each provider's token accounting onto one pair, so token
cost is comparable across providers.

## Jobs

Benchmark, compare and optimize issue real model calls and take minutes. The API
starts them as in-process jobs (`jobs.py`) and the client polls
`GET /v1/jobs/{id}` for progress and the result. One process, no broker — this
is a local tool.

## Benchmark identity

A durable record should eventually include model digest and quantization,
provider version, hardware profile, dataset revision and grader revision. Today
a report carries technique id and version, strategy, provider, model id,
dataset, example and repeat counts, per-example outputs and grades, and
timestamps. The gap is deliberate and marked.
