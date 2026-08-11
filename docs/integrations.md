# Integrations

Four optional integrations, each behind an extra. The core package works
without any of them, and `prompt-selector tracing-status` /
`GET /v1/integrations` tell you what is actually installed.

```bash
pip install -e '.[dspy]'         # DSPy optimizer backends
pip install -e '.[tracing]'      # Langfuse + OpenTelemetry/Phoenix
pip install -e '.[huggingface]'  # datasets imported from the Hub
pip install -e '.[all]'          # everything
```

promptfoo needs no Python dependency — the export writes its config, and you run
promptfoo itself (`npx promptfoo@latest`).

---

## 1. DSPy — a better search algorithm

The native optimizer is a greedy reflective loop. DSPy brings stronger search:
MIPROv2 proposes instructions and demonstrations jointly under a Bayesian
budget, GEPA evolves instructions from textual feedback while keeping a Pareto
front, BootstrapFewShot selects demonstrations from examples the baseline
already answers correctly.

**What DSPy does and does not own here.** It proposes candidates. It does not
build the prompt and it does not decide the score. Every candidate it proposes
is rendered by `PromptCompiler`, executed by the technique's own strategy, and
graded by this project's graders. So a DSPy run and a native run optimize the
same artefact against the same numbers, and the winner comes back as a plain
`TechniqueOverlay` you can compile, benchmark and export like any other.

```bash
prompt-selector optimize --model llama3.2:3b --model-class small \
  --dataset entity-extraction --technique structured.schema-first \
  --backend dspy:gepa --max-metric-calls 60 --export optimized.yaml
```

| Backend | Searches | Needs a proposer LM |
|---|---|---|
| `native` | instructions, via reflection on measured failures | yes |
| `dspy:mipro` | instructions **and** demos, jointly | yes |
| `dspy:gepa` | instructions, reflectively, Pareto-selected | yes |
| `dspy:bootstrap` | demos only | no — runs fully offline |

`--auto light|medium|heavy` sets MIPRO's and GEPA's budget; `--max-metric-calls`
caps GEPA's rollouts precisely. `--engine-model` picks a different (usually
stronger) model to write the proposals; the task itself still runs on the target
model. (`--optimizer-model` is the former name and still works.)

**Per-example metric.** DSPy needs one scalar per example, so
`example_score` collapses the graders using the task's own priorities over
quality and reliability, then applies a token penalty relative to the baseline's
measured prompt size. Optimizing for `--token-cost 0.3` therefore actually
pushes the search toward shorter prompts, rather than only showing token counts
in the final report.

**Demonstrations only help techniques that can render them.** Bootstrapping
produces demos, but a technique without a block declaring `when: has_exemplars`
has nowhere to put them. That case is reported rather than silently ignored:

```
3 demonstration(s) were bootstrapped, but structured.schema-first declares no
block with `when: has_exemplars`, so they never reach the model.
```

Techniques that do have one: `structured.few-shot-repair`,
`classification.label-rules`, `translation.glossary-context`.

**Install note.** DSPy pulls in litellm, and recent litellm builds a Rust
extension needing `rustc >= 1.94`. The extra pins `litellm<1.81` so it installs
on older toolchains; drop the pin once yours is newer.

---

## 2. promptfoo — CI gates and the model matrix

promptfoo is good at running one prompt across many providers and failing a
build on regression. Rather than reimplement that, export to it:

```bash
prompt-selector export-promptfoo \
  --techniques structured.schema-first,direct.explicit-constraints \
  --models llama3.2:3b,qwen3.5:4b --model-class small \
  --dataset entity-extraction --output promptfoo

cd promptfoo && promptfoo eval && promptfoo view
```

What lands in the directory:

```
promptfooconfig.yaml         techniques × providers × dataset
prompts/<technique>.json     the compiled messages, with {{input}} templated
prompt_selector_asserts.py   a bridge that calls this project's graders
```

Two details that keep the numbers honest:

- **The graders are the same code.** Each test carries its `expected`,
  `response_schema`, `graders` and `grader_options` as vars, and the Python
  assertion runs `run_graders` — so promptfoo reports the same `field_f1` this
  project would.
- **Native schema enforcement is exported too.** When the compiled prompt relies
  on the runtime enforcing a schema, the provider config gets Ollama's `format`
  or OpenAI's `response_format`. Without that, promptfoo would be measuring an
  unconstrained model and quietly disagreeing with `benchmark`.

**Limit.** promptfoo evaluates a single prompt per test, so a multi-call
technique exports only its first stage — and says so:

```
warning structured.few-shot-repair runs as multi_stage with 2 calls;
promptfoo will evaluate only its first stage.
```

For the whole technique, use `prompt-selector benchmark`.

---

## 3. Langfuse / Phoenix — tracing and datasets from production

Tracing wraps the provider, so it captures every call of every technique
individually — a `multi_stage` run produces one span per stage, with its own
latency and token counts.

```bash
export PROMPT_SELECTOR_TRACING=langfuse
export LANGFUSE_PUBLIC_KEY=pk-... LANGFUSE_SECRET_KEY=sk-...
export LANGFUSE_HOST=https://cloud.langfuse.com   # or your self-hosted URL

prompt-selector tracing-status
```

For Phoenix or any OTLP collector:

```bash
export PROMPT_SELECTOR_TRACING=phoenix
export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://127.0.0.1:6006/v1/traces
```

Spans carry the technique id, the stage, the validators, the provider, the
prompt and completion token counts, and the full messages — Phoenix renders them
as LLM spans via OpenInference conventions. Tracing is off unless
`PROMPT_SELECTOR_TRACING` is set, and export failures never propagate into a
run.

### Datasets from observed traffic

The point of tracing here is not dashboards, it is closing the loop: turning
what your users actually sent into a benchmark dataset.

```bash
prompt-selector import-traces --output datasets/from-prod.jsonl \
  --technique structured.schema-first --limit 200
```

Imported rows come back with `expected: null` and tagged `unreviewed`, because a
benchmark needs a gold answer and a trace does not have one. Fill them in, then:

```bash
prompt-selector benchmark --model llama3.2:3b --dataset-file datasets/from-prod.jsonl
```

`--output-as-expected` records what the model produced as the gold answer. That
is only honest for traffic a human has reviewed — otherwise you are benchmarking
a model against its own past mistakes. It is off by default for that reason.

---

## Programmatic use

```python
from prompt_selector.service import PromptSelectorService
from prompt_selector.registry import Registry
from prompt_selector.integrations.tracing import build_tracer

service = PromptSelectorService(Registry.load(), tracer=build_tracer("langfuse"))

result = await service.optimize(
    task=task,
    technique_id="structured.few-shot-repair",
    dataset_name="entity-extraction",
    backend="dspy:mipro",
    auto="light",
)

service.export_promptfoo(
    directory=Path("promptfoo"),
    task=task,
    technique_ids=["structured.schema-first"],
    dataset_name="entity-extraction",
)
```

Any object with `record(event)` and `flush()` works as a tracer, so wiring this
into an existing observability stack does not require either backend.

---

## 4. Hugging Face — datasets from public NER corpora

The shipped datasets are small and synthetic. `import-hf` converts public
token-classification corpora into benchmark examples, so the optimizer can be
measured on data somebody else built:

```bash
prompt-selector list-hf-presets
prompt-selector import-hf multiconer-en --output datasets/multiconer.jsonl --limit 200
prompt-selector benchmark --model qwen2.5:7b --dataset-file datasets/multiconer.jsonl
```

| Preset | Corpus | Fields | Licence |
|---|---|---|---|
| `multiconer-en` | [MultiCoNER v2](https://hf.co/datasets/MultiCoNER/multiconer_v2), SemEval-2023 Task 2 | people, places | CC-BY-4.0 |
| `few-nerd` | [Few-NERD](https://hf.co/datasets/DFKI-SLT/few-nerd) | people, places, organizations | CC-BY-SA-4.0 |

MultiCoNER is the closest public analogue of `entity-extraction-hard`: its whole
premise is entities that are syntactically ambiguous.

### How the conversion keeps the numbers honest

- **Gold values stay verbatim in the input.** Detokenization tracks character
  offsets and slices entity text out of the finished sentence, so the entity and
  the sentence can never disagree about spacing. Re-joining tokens separately
  would quietly produce gold the model cannot copy.
- **Unmapped entity types become empty examples, not wrong ones.** A sentence
  whose only entity is a film title yields `{"people": [], "places": []}` rather
  than a penalty for not extracting something the schema never asked for.
- **A slice of empty examples is kept on purpose** (`--empty-ratio`, default
  0.1). Dropping them would reward a prompt that guesses, because precision
  errors would have nowhere to show up.
- **Both BIO and bare labels are handled.** Few-NERD's coarse tags carry no
  `B-`/`I-` prefix, so a run of one type is one entity — the corpus's limitation,
  recorded in the preset's notes rather than hidden.

### Licensing

Each preset carries its licence and citation, printed on every import. Few-NERD
is share-alike: a dataset derived from it must keep the same licence. Attribution
is on you if you publish results.

Needs `pip install -e '.[huggingface]'`.
