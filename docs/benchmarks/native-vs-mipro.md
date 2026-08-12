# Native loop vs MIPROv2, head to head

One dataset, one split, one target model. The point is not to crown a winner but
to record what each search actually bought, and what got in the way.

## Setup

| | |
|---|---|
| Dataset | `entity-extraction-hard`, 40 examples ([rules](../datasets/entity-extraction-hard.md)) |
| Split | 26 train / 14 held out, deterministic, identical for both runs |
| Target model | `llama3.2:3b` via Ollama |
| Technique | `structured.schema-first` |
| Priorities | quality 0.4, reliability 0.3, latency 0.1, token cost 0.2 |
| Headline metric | `field_f1` — partial credit per entity, so 3 of 4 scores 0.86 |

Baseline on all 40 examples: **quality 0.777**, exact_match 0.525, reliability
1.000, 191 tokens, 0.65 s. Real headroom, unlike the 6-example demo dataset
where the baseline already scores 1.0 and no optimizer can show anything.

## Result

| Backend | Held-out quality | Δ | Model calls | Wall clock |
|---|---|---|---|---|
| baseline | 0.681 | — | — | — |
| `native` (3B proposer) | 0.681 | +0.000 | 214 | 172 s |
| `native` (27B proposer) | 0.681 | +0.000 | 133 | 873 s |
| `native` beam-2, quality-only | 0.681 | +0.000 | 268 | 201 s |
| `dspy:mipro` (3B proposer) | 0.771 | **+0.090** | 116 | 145 s |

MIPROv2 won on the same data, with roughly half the calls.

### The gain is not noise

A +0.090 delta measured once on 14 examples is well inside what a nondeterministic
model can produce by luck, so it was re-measured with three repeats — and MIPRO
was re-run from scratch, which is stochastic and produced a *different* winning
instruction:

| | field_f1 | exact_match | stability | tokens |
|---|---|---|---|---|
| baseline | 0.705 | 0.381 | 0.905 | 191 |
| MIPRO winner | **0.768** | **0.476** | 0.929 | 199 |

**+0.064 F1 and +0.095 exact match** over 42 runs per arm, from a second
independent search. The effect survives.

### What it actually found

Nothing about the annotation rules. Both winning instructions were generic
rephrasings — "You are a document extractor tasked with disambiguating entities",
or a flattened restatement of the original four steps. Neither run discovered
"a title is part of the name" or "an organisation is not a place", which is
where the baseline's errors actually are.

The obvious explanation is the proposer: the model writing the rewrites was
`llama3.2:3b`, the same 3B model being optimized. That explanation turned out to
be wrong — see below.

## Was the proposer the bottleneck? No.

The obvious hypothesis: the native loop lost because a 3B model writes bad
instructions. Testing it took two runs, and the answer was no.

**First attempt, `--optimizer-model qwen3.6:27b-mlx --timeout-seconds 300`:**
zero candidates across both rounds, 31 minutes burned.

The cause was not the model. Probed directly, it returns a perfectly usable
rewrite:

```
1. Locate evidence satisfying the target condition for each field.
2. Extract only values directly supported by this evidence; discard unrelated mentions.
3. Copy values verbatim from the input; never normalize or invent.
...
```

It just takes ~180 s per call, and every proposal blew through the 300 s
timeout on the cold 20 GB model load.

The optimizer caught the `ProviderError` and moved on silently, so the output
read `generated: 0` with no reason — indistinguishable from "the model had no
better idea", which sends you debugging the wrong thing. Fixed: discarded
proposals are counted by cause and reported.

```
6 proposal(s) discarded — proposer call failed: Ollama request failed: timeout
No proposal survived, so the search never left the baseline. That is a proposer
problem, not a result: try a stronger --optimizer-model.
```

**Second attempt, same proposer, `--timeout-seconds 900`:** three real
candidates generated, `discarded: []`, 873 s — and still **+0.000** on held-out.
None of the 27B model's rewrites beat the baseline.

| Run | Proposer | Candidates | Held-out Δ |
|---|---|---|---|
| native, rounds 3 | llama3.2:3b | 6 | +0.000 |
| native, rounds 2 | qwen3.6:27b-mlx, 300 s | 0 (all timed out) | +0.000 |
| native, rounds 2 | qwen3.6:27b-mlx, 900 s | 3 | +0.000 |
| `dspy:mipro` | llama3.2:3b | many | **+0.064** (repeat-verified) |

So the proposer is not the bottleneck. The next suspect was breadth: the native
loop was greedy, mutating only the weighted-score leader, three candidates per
round.

## Widening the beam did not close the gap either

The loop was changed to keep a beam of parents — the weighted-score leader plus
the raw-quality leader, so a candidate that answers more examples correctly but
costs more tokens stays in the search. Proposals are deduplicated, the mutation
biases now follow the task's priorities (a run weighted entirely on quality no
longer spends a third of its budget asking for a shorter prompt), and the search
history is printed with per-candidate quality.

Run with `--beam-width 2 --candidates 4 --rounds 3`, priorities set to quality
0.75 / reliability 0.25 and **zero** weight on tokens and latency, so every
proposal was aimed at accuracy:

| Round | Candidate | Origin | Quality | Tokens |
|---|---|---|---|---|
| 1 | baseline | baseline | **0.830** | 190 |
| 2 | bootstrap-demos+p3 | reflection | 0.823 | 198 |
| 2 | baseline+p1 | reflection | 0.779 | 229 |
| 2 | baseline+p2 | reflection | 0.767 | 189 |
| 2 | bootstrap-demos+p4 | reflection | 0.653 | 243 |
| 3 | bootstrap-demos+p7 | reflection | 0.817 | 209 |
| 3 | bootstrap-demos+p8 | reflection | 0.810 | 192 |
| 3 | baseline+p6 | reflection | 0.797 | 177 |
| 3 | baseline+p5 | reflection | 0.755 | 198 |

Eight rewrites from two parents, and **not one beat the baseline**. Winner:
`baseline`, held-out delta **+0.000**.

The earlier cost-weighted run made this look better than it was: its winner
`baseline+p5` edged ahead on weighted score (0.906 vs 0.903) purely by saving
18 tokens, while quality *fell* from 0.830 to 0.810. Without the per-candidate
numbers in the search history that reads as a win. It is not one.

So breadth was not the answer. Every instruction a 3B model writes for itself is
worse than the hand-written one, whether it is asked once or eight times, from
one parent or two. MIPROv2's advantage is in how it proposes — its proposer sees
the program structure and a summary of the data, and optuna searches
combinations of instruction × demonstrations — not in how many candidates it
tries.

## Appending a rule preserves the working prompt

The rewrite-only mutation had a structural failure mode: a proposer could add a
useful rule while deleting instructions that already worked. The native search
now tries both mutation types within the same candidate budget:

- `rewrite` replaces the mutable block, as before;
- `append` preserves the rendered block byte-for-byte and adds one rule justified
  by the measured failures.

Measured on 2026-08-08 with the full 200-example `entity-extraction-hard`
dataset, `qwen2.5:7b`, a deterministic 132 train / 68 held-out split, two rounds,
two candidates, beam width one, and quality-only weights:

| Candidate | Mutation | Train field_f1 | Train tokens |
|---|---|---:|---:|
| baseline | none | 0.817 | 173 |
| `baseline+p1` | rewrite | 0.806 | 188 |
| `baseline+p2` | append | **0.830** | 192 |

The append candidate won, and its gain survived held-out validation:

| Metric | Baseline | Append winner | Delta |
|---|---:|---:|---:|
| field_f1 | 0.806 | **0.817** | **+0.011** |
| reliability | 1.000 | 1.000 | +0.000 |
| mean tokens | 172.35 | 190.74 | +18.39 |
| mean latency (s) | 0.805 | 0.794 | -0.011 |

The winning addition was generic — "Do not infer or add evidence for any field;
use only what is explicitly given" — rather than one of the dataset's annotation
rules. The result is positive but small, so it does not overturn the stronger
MIPROv2 result above. It does show the intended mechanism: the original four-step
procedure remains intact, the append is measured as a separate candidate, and
the held-out delta is no longer negative.

The run made 798 real model calls and took 655.98 seconds. The CLI originally
reported 530 because it omitted bootstrap and held-out validation calls; the
counter was corrected as part of this change, without changing candidate scores
or the winner.

```bash
prompt-playoff optimize --model qwen2.5:7b --model-class medium \
  --dataset entity-extraction-hard --task structured_extraction \
  --technique structured.schema-first --backend native --rounds 2 \
  --candidates 2 --beam-width 1 --quality 1 --reliability 0 \
  --latency 0 --token-cost 0 --timeout-seconds 120
```

What the beam change did buy: the search history is now legible, wasted brevity
proposals are gone when tokens are not weighted, repeated rewrites are discarded
instead of re-measured, and a winner that is the baseline under another name
says so.

One more honest detail: the native winner in both 27B runs was
`bootstrap-demos`, which for `structured.schema-first` is the baseline under
another name — the technique has no `when: has_exemplars` block, so the
bootstrapped demonstrations never reach the model. The run now says so:

```
The winner carries 3 demonstration(s), but structured.schema-first declares no
block with `when: has_exemplars`, so they never reach the model — this result is
the baseline under another name.
```

## Reading this honestly

- MIPROv2 beat the native greedy loop on this dataset, verified with repeats.
  One dataset and one target model is not a general claim.
- The absolute numbers are low (0.77 F1) because a 3B model is genuinely bad at
  these distinctions. That is the point of the dataset.
- Neither optimizer recovered the annotation rules. Neither a 27B proposer nor a
  wider beam changed that: in 8 accuracy-aimed rewrites from 2 parents, the best
  candidate scored 0.823 against the baseline's 0.830.
- Read the search history, not just the winner. A candidate can top the weighted
  score while being worse at the task, if tokens carry weight.
- A slow proposer needs a timeout matched to it. `--timeout-seconds` covers both
  the task calls and the proposal calls, and a cold 20 GB model takes minutes.
- `dspy:bootstrap` is irrelevant for `structured.schema-first`: the technique
  has no `when: has_exemplars` block, so demonstrations cannot reach the model.
  The run says so instead of pretending to improve.

## Reproducing

```bash
python scripts/build_hard_dataset.py

prompt-playoff benchmark --model llama3.2:3b --model-class small \
  --dataset entity-extraction-hard --technique structured.schema-first

prompt-playoff optimize --model llama3.2:3b --model-class small \
  --dataset entity-extraction-hard --technique structured.schema-first \
  --backend native --rounds 3 --candidates 3

prompt-playoff optimize --model llama3.2:3b --model-class small \
  --dataset entity-extraction-hard --technique structured.schema-first \
  --backend dspy:mipro --auto light
```

Both backends split the dataset identically, so the comparison holds without
extra bookkeeping.
