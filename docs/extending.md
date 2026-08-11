# Extending the registry

Three extension points, in order of how often you will reach for them:

| You want to add | You write | Python needed |
|---|---|---|
| A prompt technique | one YAML file | no |
| A benchmark dataset | one JSONL file | no |
| A scoring metric (grader) | one function + decorator | yes, ~10 lines |
| An execution pattern (strategy) | one class + decorator | yes, ~40 lines |

Run `prompt-selector capabilities` to print everything currently available to a
YAML file: strategies, graders, aggregators, datasets.

## 1. A new technique

```bash
prompt-selector new-technique structured.my-technique --title "My technique"
prompt-selector validate-registry
```

The scaffold writes into `src/prompt_selector/data/techniques/`. Point
`PROMPT_SELECTOR_REGISTRY` at another directory to keep your techniques outside
this repository.

### The prompt is data

A recipe declares **blocks**. Each block becomes one titled section of the user
message, rendered in declaration order:

```yaml
recipe:
  system: One sentence stating the behaviour this technique enforces.
  variables:
    bullet_count: "5"
  blocks:
    - name: role
      title: OBJECTIVE
      body: "Summarize the input into exactly {bullet_count} bullets.\n"
    - name: contract_embedded
      title: OUTPUT CONTRACT
      when: embedded_schema
      body: "Return JSON matching:\n{schema_json}\n"
    - name: input
      title: INPUT
      body: "{input}\n"
```

**Placeholders** are a closed set, so a typo is a lint error rather than a
literal `{bullet_kount}` reaching the model:

| Placeholder | Value |
|---|---|
| `{input}` | the task input |
| `{task_type}`, `{domain}`, `{complexity}`, `{output_contract}` | task profile fields |
| `{schema_json}` | the response schema, pretty-printed |
| `{schema_fields}` | the schema as a readable field list |
| `{instructions}` | `recipe.instructions` as a numbered list |
| `{exemplars}` | few-shot demonstrations supplied with the request |
| `{model_id}`, `{max_calls}`, `{max_output_tokens}`, `{validators}` | execution context |
| anything in `recipe.variables` | your own, overridable per request |

Write `{{` and `}}` for literal braces.

**`suits`** is what makes selection about the request instead of its task type.
Every request carries a *shape* — one to four of `multi_step`, `verifiable`,
`underspecified`, `long_input`, `exact_format`, `has_examples`, `open_ended`,
`high_stakes`, `computational` — and a recipe declares which of them it is built
for:

```yaml
suits:
  - multi_step
  - high_stakes
```

Traits are weighted by how rare the claim is across the registry, so declaring a
trait eight other recipes already claim buys little and declaring a rare one that
actually fits buys a lot. Keep the list to four; `validate-registry` fails above
that, because a recipe that suits everything ranks first for everything and has
said nothing. Shape is applied *within* a task type — it can reorder the recipes
that fit the task, never promote one that does not.

**`requires_supplied_evidence: true`** marks a recipe that answers only from
material pasted into the prompt. The selector then rejects it for any task whose
`constraints.retrieval_required` is set — a task that has to find its own
sources would otherwise get a prompt telling the model to quote evidence nobody
supplied. Set it on grounding and long-context recipes; leave it off for
tool-using ones, which get a ranking bonus on exactly those tasks instead.

**Runtime placeholders** survive compilation untouched and are filled during
execution: `{previous}` (multi-stage), `{chunk}` and `{partials}` (map-reduce).
A compiled prompt shows them verbatim so you can see where runtime data lands.

**Conditions** (`when:`) come from a closed vocabulary too: `always`,
`has_schema`, `native_schema`, `embedded_schema`, `strict_json`, `free_text`,
`has_exemplars`, `supplied_material`, `topic_only`, `tools_allowed`,
`requires_validation`, `has_domain`, `reasoning_control`. A block whose condition
is false, or which renders empty, is dropped.

`supplied_material` and `topic_only` are the two halves of one question: does the
prompt carry the text to work on? "Answer only from the input" is right when it
does and tells the model to refuse when it does not, so a recipe that says
anything like it wants a block for each case.

### Multi-call techniques

`execution.strategy` decides how the compiled stages become provider calls.

```yaml
execution:
  strategy: multi_stage
  stages:
    - name: draft
      blocks: [role, contract_embedded, input]
    - name: revise
      blocks: [criteria, revision_task]
      system: Revise only substantiated defects.   # overrides recipe.system
      carries_schema: false                        # this stage is free text
```

Shipped strategies:

| Strategy | Params | Calls |
|---|---|---|
| `single` | — | 1 |
| `multi_stage` | `final_stage` | one per declared stage, `{previous}` chained |
| `self_consistency` | `samples`, `temperature`, `aggregator` | `samples` |
| `map_reduce` | `chunk_chars`, `overlap_chars`, `max_chunks` | one per chunk, plus a reduce |
| `tool_loop` | `max_iterations` | up to `max_iterations`, tools executed between |

Aggregators for `self_consistency`: `majority_vote`, `json_field_vote`. Both
report a **measured** agreement ratio in the execution trace.

### Validators must be measurable

`recipe.validators` are grader names. Listing a grader that does not exist is a
lint warning, because an unmeasurable validator is decoration:

```
[warning] my.technique: validator 'vibes' has no grader, so it cannot be measured
```

## 2. A new dataset

Drop a `.jsonl` file into `src/prompt_selector/data/datasets/`. One example per
line:

```json
{"id": "cls-001", "input": "Charged twice this month.", "expected": "billing",
 "response_schema": {"type": "object", "properties": {"label": {"type": "string"}}, "required": ["label"]},
 "graders": ["label_accuracy", "json_schema"],
 "grader_options": {"labels": ["billing", "bug", "feature_request", "account"]},
 "variables": {"label_set": "billing, bug, feature_request, account"},
 "exemplars": [{"input": "...", "output": "..."}],
 "tags": ["short"]}
```

Only `id` and `input` are required. Omit `graders` and the runner picks them
from the data: an `expected` object gets `field_f1` + `exact_match`, an
`expected` string gets `label_accuracy`, a `response_schema` gets
`json_validity` + `json_schema` + `schema_shape`. The technique's own validators
are always added on top; a grader that cannot apply returns nothing rather than
a zero.

## 3. A new grader

```python
from prompt_selector.graders import GradeContext, grader


@grader("bullet_count")
def bullet_count(ctx: GradeContext) -> float | None:
    target = (ctx.options or {}).get("bullets")
    if not target:
        return None  # not applicable: contributes nothing
    found = sum(1 for line in ctx.output.splitlines() if line.strip().startswith("-"))
    return 1.0 if found == int(target) else 0.0
```

`GradeContext` carries `output`, `parsed` (JSON if parseable), `expected`,
`response_schema`, `options` (from `grader_options`) and `trace` (the real call
records, for metrics like agreement or tool success).

Return `None` when the grader cannot apply. Add the name to
`RELIABILITY_GRADERS` if it measures contract compliance rather than answer
quality, and to `QUALITY_PREFERENCE` if it can serve as the headline quality
number.

## 4. A new strategy

```python
from prompt_selector.strategies import Strategy, register_strategy, call_once


class BestOfNParams(BaseModel):
    model_config = {"extra": "forbid"}
    samples: int = 3


@register_strategy
class BestOfN(Strategy):
    name = "best_of_n"
    Params = BestOfNParams
    required_stages = ()  # or ("map", "reduce") style requirements

    def expected_calls(self, params, stage_count):
        return params.samples

    async def execute(
        self, program, task, provider, timeout_seconds
    ): ...  # return an ExecutionTrace with one CallRecord per real call
```

Register it and every technique can select `strategy: best_of_n` from YAML.
`validate-registry` will then check its params for you.

## What lint checks

`prompt-selector validate-registry` (and `GET /v1/lint`) verifies, per technique:

1. the strategy exists and its params validate
2. stages required by the strategy are declared
3. every placeholder resolves
4. every validator maps to a real grader
5. `min_calls` does not exceed what the strategy will actually issue
6. the recipe compiles against a synthetic task, renders a non-empty user
   message, leaves no `{input}` behind, and includes the task input
7. `suits` names at most four request shapes, and names at least one (a warning:
   an existing registry keeps loading, but the recipe can never win on shape)
8. every stage after the first reads `{previous}`. A stage that reads nothing
   from the stage before it is a second model call doing work that belongs in
   the first prompt — make it another block instead. Claiming speed or thrift
   (`token_efficiency` or `latency_efficiency` at 0.7 or above, or the
   `token-efficient` tag) while declaring two calls is a warning for the same
   reason: the extra round trip spends what the recipe says it saves.

`--strict` also fails on warnings. CI runs it.
