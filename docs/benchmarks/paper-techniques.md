# Techniques from the literature, measured

Thirteen techniques were added from [The Prompt Report](https://arxiv.org/abs/2406.06608)
and three later papers. This is what happened when they were run.

## Extraction: eleven of twelve lost to the baseline

`few-nerd`, 40-example slice, `qwen2.5:7b`, priorities quality 0.7 / reliability 0.3.

| Technique | Quality | Δ vs baseline | Tokens | Seconds |
|---|---:|---:|---:|---:|
| `reasoning.re-reading` | 0.544 | **+0.012** | 214 | 1.35 |
| `structured.schema-first` *(baseline)* | 0.532 | — | 210 | 1.08 |
| `reasoning.chain-of-draft` | 0.514 | −0.018 | 301 | 2.32 |
| `few-shot.contrastive-cot` | 0.504 | −0.029 | 188 | 1.07 |
| `reasoning.step-back` | 0.497 | −0.036 | 367 | 3.09 |
| `verification.chain-of-verification` | 0.465 | −0.068 | 703 | 6.76 |
| `verification.backward-check` | 0.463 | −0.069 | 450 | 4.68 |
| `reasoning.self-ask` | 0.456 | −0.076 | 447 | 4.18 |
| `reasoning.system2-attention` | 0.452 | −0.080 | 290 | 2.48 |
| `reasoning.zero-shot-cot` | 0.443 | −0.089 | 720 | 8.14 |
| `reasoning.metacognitive` | 0.426 | −0.107 | 656 | 7.31 |
| `reasoning.rephrase-and-respond` | 0.421 | −0.111 | 559 | 6.38 |

The ordering tracks token spend almost exactly, in the wrong direction: the more
a technique thinks, the worse it scores.

**The likely mechanism.** Entity extraction is reading, not reasoning. An
intermediate stage lets the model restate the input in its own words, and the
final stage then answers from that restatement rather than from the original.
The restatement loses exact surface forms — and `field_f1` requires them
verbatim. Reasoning does not help you copy.

`verification.chain-of-verification` is the clearest case: three calls and 703
tokens to score 0.068 *below* a single 210-token call.

**Chain of Draft half delivered.** Against `zero-shot-cot` it is 2.4× cheaper (301
vs 720 tokens) and better (0.514 vs 0.443), so within the chain-of-thought
family its claim holds. But the whole family loses to not reasoning at all here.

## What this does not show

- One task type, one model, 40 examples. Differences under about 0.04 are noise
  at that size; only the tail below −0.07 is safely real.
- Most of these techniques are published for reasoning, research or ambiguous
  classification. Judging them on extraction is like testing a translator on
  arithmetic. The classification run below is the fairer test for several.

## The rule this suggests

Before adding a technique because a paper reports a gain, check that the paper's
task resembles yours. A technique that helps multi-step arithmetic can actively
hurt verbatim copying, and the registry now has measurements showing exactly
that.

## Reproducing

```bash
python - <<'EOF'
from prompt_selector.evals import load_jsonl
from prompt_selector.registry import Registry
import pathlib
rows = load_jsonl(Registry.load().dataset_path("few-nerd"))
pathlib.Path("/tmp/few-nerd-40.jsonl").write_text(
    "\n".join(r.model_dump_json() for r in rows[::5][:40]) + "\n")
EOF

prompt-selector compare --model qwen2.5:7b --model-class medium \
  --dataset-file /tmp/few-nerd-40.jsonl \
  --techniques structured.schema-first,reasoning.re-reading,reasoning.chain-of-draft,reasoning.zero-shot-cot \
  --quality 0.7 --reliability 0.3 --latency 0 --token-cost 0
```
