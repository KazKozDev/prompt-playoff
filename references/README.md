# References

Papers downloaded from arXiv, kept for building out the technique registry.

The PDFs themselves are **not committed** — they are third-party works under
their own licences, and a repository is the wrong place to redistribute them.
This index is committed instead; `make papers` fetches them again.

## The catalogue

| arXiv | Pages | Paper |
|---|---:|---|
| [2406.06608](https://arxiv.org/abs/2406.06608) | 80 | **The Prompt Report: A Systematic Survey of Prompt Engineering Techniques** — a taxonomy of **58 text-based techniques**, plus 40 more for other modalities. The one worth reading first. |
| [2604.14197](https://arxiv.org/abs/2604.14197) | 40 | **The PICCO Framework for LLM Prompting: A Taxonomy and Reference Architecture** — closest in spirit to this project: a taxonomy paired with an architecture rather than a list. |
| [2407.12994](https://arxiv.org/abs/2407.12994) | 39 | **A Survey of Prompt Engineering Methods in LLMs for Different NLP Tasks** — maps techniques onto task types, which is exactly what `strong_tasks` / `acceptable_tasks` encode. |
| [2502.11560](https://arxiv.org/abs/2502.11560) | 19 | **A Survey of Automatic Prompt Engineering: An Optimization Perspective** — the search-algorithm side; relevant to `optimizer.py` and the DSPy backend. |
| [2401.14043](https://arxiv.org/abs/2401.14043) | 16 | **Towards Goal-oriented Prompt Engineering for LLMs** — selecting a technique from the goal, which is what the selector does. |
| [2402.07927](https://arxiv.org/abs/2402.07927) | 12 | **A Systematic Survey of Prompt Engineering in LLMs: Techniques and Applications** — ~29 techniques, compact. |
| [2312.03740](https://arxiv.org/abs/2312.03740) | 10 | **A Survey on Prompting Techniques in LLMs** — short overview. |

## What this is for

The registry ships 61 techniques. Adding one is a single YAML file
([docs/extending.md](../docs/extending.md)), so these surveys are the shortlist
of what to add next — and, more importantly, the source for the
`benchmark_priors` and `evidence_level` fields, which should point at published
evidence rather than at a guess.

`2406.06608` is the one to mine: its 58 techniques are already grouped into
families that line up with the registry's `family` field.

## Re-downloading

```bash
make papers
```

Downloads on a 3-second delay, per arXiv's request for automated access.
