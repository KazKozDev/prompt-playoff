"""Automatic prompt optimization driven by measured numbers.

The loop is the one DSPy (MIPRO/GEPA), OPRO and EvoPrompt converged on, adapted
to this project's registry:

    seed candidates -> benchmark each on a train split -> score with the task's
    own priorities over measured quality, reliability, latency and tokens ->
    reflect on the worst failures to propose better instructions -> repeat ->
    verify the winner on a held-out split.

Nothing is scored by an LLM judge and nothing is estimated: every number comes
from :mod:`prompt_selector.evals`, so "the prompt got better" means it got
better on data you can inspect.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

from prompt_selector.compiler import PromptCompiler
from prompt_selector.domain import (
    CompiledPrompt,
    Exemplar,
    Message,
    ModelProfile,
    TaskProfile,
    TechniqueSpec,
)
from prompt_selector.evals import (
    BenchmarkExample,
    BenchmarkReport,
    BenchmarkRunner,
    Scorecard,
)
from prompt_selector.providers import ModelProvider, ProviderError


class TechniqueOverlay(BaseModel):
    """A candidate edit to a technique's recipe. The technique itself is never mutated."""

    system: str | None = None
    block_bodies: dict[str, str] = Field(default_factory=dict)
    block_appends: dict[str, str] = Field(default_factory=dict)
    exemplars: list[Exemplar] = Field(default_factory=list)

    def apply(self, technique: TechniqueSpec) -> TechniqueSpec:
        patched = technique.model_copy(deep=True)
        if self.system:
            patched.recipe.system = self.system
        for block in patched.recipe.blocks:
            if block.name in self.block_bodies:
                block.body = self.block_bodies[block.name]
            if rule := self.block_appends.get(block.name):
                separator = "" if block.body.endswith("\n") else "\n"
                block.body = f"{block.body}{separator}{rule.strip()}\n"
        if self.exemplars:
            patched.recipe.exemplars = list(self.exemplars)
        return patched


class Candidate(BaseModel):
    id: str
    technique_id: str
    origin: str
    overlay: TechniqueOverlay = Field(default_factory=TechniqueOverlay)
    train: Scorecard | None = None
    score: float | None = None
    prompt_tokens: float | None = None


class OptimizationRound(BaseModel):
    round: int
    evaluated: list[Candidate]
    best_id: str
    best_score: float


class OptimizationResult(BaseModel):
    task_type: str
    model_id: str
    dataset: str
    train_size: int
    validation_size: int
    rounds: list[OptimizationRound]
    baseline_id: str
    winner: Candidate
    baseline_validation: Scorecard
    winner_validation: Scorecard
    improvement: dict[str, float]
    pareto_front: list[Candidate]
    compiled_prompt: dict[str, Any] = Field(default_factory=dict)
    exported_technique: dict[str, Any] = Field(default_factory=dict)
    total_calls: int = 0
    elapsed_seconds: float = 0.0
    priorities: dict[str, float] = Field(default_factory=dict)
    #: Which search algorithm produced this: "native", "dspy:mipro", "dspy:gepa"…
    backend: str = "native"
    #: Which model wrote the candidate prompts, and whether that is the model the
    #: numbers describe. A result that cannot answer this is not interpretable.
    engine_model_id: str = ""
    engine_is_target: bool = True
    notes: list[str] = Field(default_factory=list)


ProgressCallback = Callable[[dict[str, Any]], None]
#: Optimizer search backends the CLI and API accept.
BACKENDS = ("native", "dspy:mipro", "dspy:gepa", "dspy:bootstrap")

#: The block an optimizer is allowed to rewrite, per technique family shape.
#: Instruction-bearing blocks only — contracts and inputs stay untouched so a
#: candidate cannot "win" by dropping the output format.
MUTABLE_BLOCKS = ("procedure", "rules", "constraints", "protocol", "criteria", "boundaries")

ACCURACY_BIASES = (
    "Make the instructions more explicit about the failure the model just made. "
    "Add a rule that would have prevented it.",
    "Reorder the instructions so the most commonly violated rule comes first, and state it "
    "as a hard prohibition rather than a preference.",
    "Name the distinction the model is getting wrong and give it a decision procedure for "
    "that specific case. Be concrete, not encouraging.",
)
BREVITY_BIAS = (
    "Make the instructions shorter. Remove every sentence that does not change behaviour, "
    "but keep all binding constraints. Fewer prompt tokens is the point."
)
#: Below this weight, spending proposals on shortening the prompt is waste.
BREVITY_THRESHOLD = 0.15


def mutation_biases(task: TaskProfile) -> tuple[str, ...]:
    """Spend the proposal budget on what the task is actually being scored for.

    A run weighted entirely on quality should not burn a third of its proposals
    asking for a shorter prompt — that trades away the thing being optimized.
    """
    priorities = task.priorities.normalized()
    if priorities.token_cost + priorities.latency >= BREVITY_THRESHOLD:
        return (*ACCURACY_BIASES[:2], BREVITY_BIAS, ACCURACY_BIASES[2])
    return ACCURACY_BIASES


class PromptOptimizer:
    def __init__(
        self,
        provider: ModelProvider,
        engine_provider: ModelProvider | None = None,
        engine_model: ModelProfile | None = None,
        compiler: PromptCompiler | None = None,
    ) -> None:
        self.provider = provider
        #: Falls back to the model under test, which means the model grades a prompt
        #: it wrote for itself. Legal, but the result says so out loud.
        self.engine_provider = engine_provider or provider
        self.engine_model = engine_model
        self.compiler = compiler or PromptCompiler()
        self.runner = BenchmarkRunner(provider, self.compiler)
        #: Why proposals were discarded, surfaced in the result rather than swallowed.
        self.proposal_failures: list[str] = []
        self.proposals_accepted = 0
        self._proposal_seq = 0

    async def optimize(
        self,
        task: TaskProfile,
        technique: TechniqueSpec,
        dataset: list[BenchmarkExample],
        rounds: int = 2,
        candidates_per_round: int = 3,
        repeats: int = 1,
        validation_ratio: float = 0.34,
        timeout_seconds: float = 120,
        dataset_name: str = "inline",
        beam_width: int = 2,
        progress: ProgressCallback | None = None,
    ) -> OptimizationResult:
        if len(dataset) < 2:
            raise ValueError("Optimization needs at least two examples to split")
        started = time.perf_counter()
        train, validation = _split(dataset, validation_ratio)
        priorities = task.priorities.normalized()
        call_count = 0

        baseline = Candidate(id="baseline", technique_id=technique.id, origin="baseline")
        population: list[Candidate] = [baseline]

        bootstrapped, bootstrap_calls = await self._bootstrap(
            task, technique, train, timeout_seconds, dataset_name
        )
        call_count += bootstrap_calls
        if bootstrapped is not None:
            population.append(bootstrapped)

        evaluated: dict[str, Candidate] = {}
        history: list[OptimizationRound] = []
        reports: dict[str, BenchmarkReport] = {}

        for round_index in range(1, rounds + 1):
            pending = [item for item in population if item.id not in evaluated]
            for candidate in pending:
                report = await self._evaluate(
                    candidate, task, technique, train, repeats, timeout_seconds, dataset_name
                )
                reports[candidate.id] = report
                candidate.train = report.scorecard
                candidate.prompt_tokens = report.scorecard.mean_prompt_tokens
                call_count += report.scorecard.runs * max(1, int(report.scorecard.mean_calls))
                evaluated[candidate.id] = candidate
                if progress:
                    progress(
                        {
                            "phase": "evaluate",
                            "round": round_index,
                            "candidate": candidate.id,
                            "origin": candidate.origin,
                        }
                    )

            _rescore(list(evaluated.values()), priorities)
            ranked = sorted(evaluated.values(), key=lambda item: item.score or 0.0, reverse=True)
            history.append(
                OptimizationRound(
                    round=round_index,
                    evaluated=[item.model_copy(deep=True) for item in ranked],
                    best_id=ranked[0].id,
                    best_score=ranked[0].score or 0.0,
                )
            )

            if round_index == rounds:
                break

            parents = select_parents(ranked, beam_width)
            before = len(self.proposal_failures)
            proposal_seq_before = self._proposal_seq
            proposals: list[Candidate] = []
            # Budget is per round, spread round-robin over the beam, so widening
            # the search costs breadth rather than extra model calls.
            for index, parent in enumerate(parents):
                share = candidates_per_round // len(parents) + (
                    1 if index < candidates_per_round % len(parents) else 0
                )
                if share <= 0:
                    continue
                proposals += await self._propose(
                    task,
                    technique,
                    parent,
                    reports.get(parent.id),
                    share,
                    timeout_seconds,
                    seen=self._instructions_seen(evaluated.values(), technique),
                    train=train,
                    evaluated=list(evaluated.values()),
                )
            # Count attempted proposer calls too: an empty, repeated, or malformed
            # answer still consumed a real model request.
            call_count += self._proposal_seq - proposal_seq_before
            population = list(evaluated.values()) + proposals
            if progress:
                progress(
                    {
                        "phase": "propose",
                        "round": round_index,
                        "parents": [item.id for item in parents],
                        "generated": len(proposals),
                        "discarded": self.proposal_failures[before:],
                    }
                )

        ranked = sorted(evaluated.values(), key=lambda item: item.score or 0.0, reverse=True)
        winner = ranked[0]

        baseline_validation_report = await self._evaluate(
            baseline, task, technique, validation, repeats, timeout_seconds, dataset_name
        )
        baseline_validation = baseline_validation_report.scorecard
        call_count += _report_calls(baseline_validation_report)
        if winner.id == baseline.id:
            winner_validation = baseline_validation
        else:
            winner_validation_report = await self._evaluate(
                winner, task, technique, validation, repeats, timeout_seconds, dataset_name
            )
            winner_validation = winner_validation_report.scorecard
            call_count += _report_calls(winner_validation_report)

        winning_technique = winner.overlay.apply(technique)
        preview = self.compiler.compile(
            task=task,
            technique=winning_technique,
            user_input=dataset[0].input,
            response_schema=dataset[0].response_schema,
            variables=dataset[0].variables,
            exemplars=[*dataset[0].exemplars, *winner.overlay.exemplars],
        )

        return OptimizationResult(
            task_type=task.task_type.value,
            model_id=task.model.model_id,
            dataset=dataset_name,
            train_size=len(train),
            validation_size=len(validation),
            rounds=history,
            baseline_id=baseline.id,
            winner=winner,
            baseline_validation=baseline_validation,
            winner_validation=winner_validation,
            improvement={
                "quality": round(winner_validation.quality - baseline_validation.quality, 4),
                "reliability": round(
                    winner_validation.reliability - baseline_validation.reliability, 4
                ),
                "mean_total_tokens": round(
                    winner_validation.mean_total_tokens - baseline_validation.mean_total_tokens, 2
                ),
                "mean_latency_seconds": round(
                    winner_validation.mean_latency_seconds
                    - baseline_validation.mean_latency_seconds,
                    4,
                ),
            },
            pareto_front=pareto_front(list(evaluated.values())),
            compiled_prompt={
                "strategy": preview.strategy,
                "expected_calls": preview.expected_calls,
                "stages": [
                    {
                        "stage": stage.stage,
                        "system": stage.messages[0].content,
                        "user": stage.messages[1].content,
                    }
                    for stage in preview.stages
                ],
            },
            exported_technique=export_technique(winning_technique, winner),
            total_calls=call_count,
            elapsed_seconds=round(time.perf_counter() - started, 2),
            priorities=priorities.model_dump(),
            engine_model_id=(self.engine_model or task.model).model_id,
            engine_is_target=self.engine_model is None,
            notes=[*self._engine_note(task), *self._diagnosis(technique, winner)],
        )

    def _engine_note(self, task: TaskProfile) -> list[str]:
        """Self-optimization is allowed, but it is never left implicit."""
        if self.engine_model is not None:
            return []
        return [
            f"Candidate prompts were written by {task.model.model_id}, the same model the "
            "numbers describe. Part of the gain may be that model's own phrasing rather "
            "than a better prompt; set --engine-model to have a different model propose."
        ]

    def _diagnosis(self, technique: TechniqueSpec, winner: Candidate) -> list[str]:
        from collections import Counter

        from prompt_selector.domain import BlockCondition

        notes: list[str] = []
        counts = Counter(self.proposal_failures)
        notes += [
            f"{count} proposal(s) discarded — {reason}" for reason, count in counts.most_common()
        ]
        if self.proposal_failures and not self.proposals_accepted:
            notes.append(
                "No proposal survived, so the search never left the baseline. That is a "
                "proposer problem, not a result: try a stronger --engine-model."
            )
        renders_demos = any(
            block.when is BlockCondition.has_exemplars for block in technique.recipe.blocks
        )
        if winner.overlay.exemplars and not renders_demos:
            notes.append(
                f"The winner carries {len(winner.overlay.exemplars)} demonstration(s), but "
                f"{technique.id} declares no block with `when: has_exemplars`, so they never "
                "reach the model — this result is the baseline under another name."
            )
        return notes

    # -- candidate generation ----------------------------------------------- #

    async def _bootstrap(
        self,
        task: TaskProfile,
        technique: TechniqueSpec,
        train: list[BenchmarkExample],
        timeout_seconds: float,
        dataset_name: str,
    ) -> tuple[Candidate | None, int]:
        """DSPy-style bootstrap: keep the train items the baseline already nails as demos."""
        graded = [item for item in train if item.expected is not None]
        if not graded:
            return None, 0
        report = await self.runner.run(
            dataset=graded,
            task=task,
            technique=technique,
            repeats=1,
            timeout_seconds=timeout_seconds,
            dataset_name=dataset_name,
        )
        by_id = {item.id: item for item in graded}
        wins = [run for run in report.runs if _primary(run.grades) >= 0.999]
        if not wins:
            return None, _report_calls(report)
        # Auto-CoT's point: demonstrations that are similar to each other teach
        # the model one case three times. Picking cheap-first did exactly that,
        # because short inputs resemble short inputs. Spread them instead.
        wins = diverse_sample(
            wins,
            key=lambda run: by_id[run.example_id].input if run.example_id in by_id else "",
            k=3,
        )
        exemplars = [
            Exemplar(input=by_id[run.example_id].input, output=run.output.strip())
            for run in wins
            if run.example_id in by_id
        ]
        return (
            Candidate(
                id="bootstrap-demos",
                technique_id=technique.id,
                origin="bootstrap",
                overlay=TechniqueOverlay(exemplars=exemplars),
            ),
            _report_calls(report),
        )

    @staticmethod
    def _instructions_seen(candidates, technique: TechniqueSpec) -> set[str]:
        """Normalized instruction text already evaluated, so the beam cannot
        spend a whole round re-testing something it has measured."""
        target = next(
            (block.name for block in technique.recipe.blocks if block.name in MUTABLE_BLOCKS), None
        )
        if target is None:
            return set()
        original = next(
            (block.body for block in technique.recipe.blocks if block.name == target), ""
        )
        seen = {" ".join(original.split())}
        for candidate in candidates:
            patched = candidate.overlay.apply(technique)
            body = next((block.body for block in patched.recipe.blocks if block.name == target), "")
            if body:
                seen.add(" ".join(body.split()))
        return seen

    async def _propose(
        self,
        task: TaskProfile,
        technique: TechniqueSpec,
        parent: Candidate,
        report: BenchmarkReport | None,
        count: int,
        timeout_seconds: float,
        seen: set[str] | None = None,
        train: list[BenchmarkExample] | None = None,
        evaluated: list[Candidate] | None = None,
    ) -> list[Candidate]:
        base = parent.overlay.apply(technique)
        target = next((block for block in base.recipe.blocks if block.name in MUTABLE_BLOCKS), None)
        if target is None:
            return []

        seen = set(seen or ())
        failures = _failure_digest(report, train)
        biases = mutation_biases(task)
        skeleton = technique_digest(technique, target.name)
        tags = tag_digest(report, train or [])
        history = history_digest(evaluated or [], target.name)
        proposals: list[Candidate] = []
        for _ in range(count):
            # The bias rotates across the whole run, not within one parent, so a
            # wider beam explores different rewrite directions instead of
            # repeating the same request once per parent.
            mutation = ("rewrite", "append")[self._proposal_seq % 2]
            bias = biases[self._proposal_seq % len(biases)]
            self._proposal_seq += 1
            try:
                rewritten = await self._ask_for_instructions(
                    task=task,
                    current=target.body,
                    bias=bias,
                    failures=failures,
                    scorecard=parent.train,
                    timeout_seconds=timeout_seconds,
                    skeleton=skeleton,
                    tags=tags,
                    history=history,
                    mutation=mutation,
                )
            except ProviderError as exc:
                # A silent skip here looks identical to "the model had no better
                # idea", which sends you debugging the wrong thing.
                self.proposal_failures.append(f"proposer call failed: {exc}")
                continue
            if not rewritten:
                self.proposal_failures.append(f"proposer returned an empty {mutation}")
                continue
            if mutation == "rewrite" and rewritten.strip() == target.body.strip():
                self.proposal_failures.append("proposer returned the original instruction")
                continue
            overlay = parent.overlay.model_copy(deep=True)
            if mutation == "rewrite":
                # The rewritten text already includes the parent's rendered append rules.
                # Keeping them separately would append them a second time.
                overlay.block_appends.pop(target.name, None)
                overlay.block_bodies[target.name] = rewritten.strip() + "\n"
            else:
                previous = overlay.block_appends.get(target.name, "")
                separator = "\n" if previous.strip() else ""
                overlay.block_appends[target.name] = (
                    f"{previous.rstrip()}{separator}{rewritten.strip()}\n"
                )
            rendered = overlay.apply(technique)
            rendered_body = next(
                block.body for block in rendered.recipe.blocks if block.name == target.name
            )
            normalized = " ".join(rendered_body.split())
            if normalized in seen:
                self.proposal_failures.append("proposer repeated an instruction already measured")
                continue
            seen.add(normalized)
            self.proposals_accepted += 1
            proposals.append(
                Candidate(
                    id=f"{parent.id}+p{self._proposal_seq}",
                    technique_id=technique.id,
                    origin=f"reflection:{mutation}:{parent.id}",
                    overlay=overlay,
                )
            )
        return proposals

    async def _ask_for_instructions(
        self,
        task: TaskProfile,
        current: str,
        bias: str,
        failures: str,
        scorecard: Scorecard | None,
        timeout_seconds: float,
        skeleton: str = "",
        tags: str = "",
        history: str = "",
        mutation: str = "rewrite",
    ) -> str:
        action = "adding ONE new rule to" if mutation == "append" else "rewriting"
        sections = [
            f"You are {action} ONE block inside a larger prompt used for a "
            f"{task.task_type.value} task. The other blocks are fixed."
        ]
        if skeleton:
            sections.append(
                "PROMPT SKELETON — the full prompt is assembled from these blocks, in order:\n"
                f"{skeleton}\n"
                "Never restate what a fixed block already says."
            )
        sections.append(f"CURRENT TEXT OF THE BLOCK\n{current.strip()}")
        if scorecard:
            sections.append(
                f"MEASURED PERFORMANCE\nquality {scorecard.quality:.2f}, "
                f"reliability {scorecard.reliability:.2f}, "
                f"{scorecard.mean_prompt_tokens:.0f} prompt tokens, "
                f"{scorecard.mean_latency_seconds:.2f}s per example."
            )
        if tags:
            # A 3B proposer will happily read bare slugs as schema field names and
            # write rules about them, so say plainly what these labels are.
            sections.append(
                "WEAKEST CASE TYPES — these are analyst labels for KINDS OF INPUT, not fields "
                "in the output and not words that appear in the data. They say which "
                "distinction the prompt keeps getting wrong. Never mention these labels in "
                "your rewrite; write the rule that decides the case instead.\n" + tags
            )
        sections.append(f"CONCRETE FAILURES\n{failures or 'None recorded.'}")
        if history:
            sections.append(
                "ALREADY TRIED, WITH MEASURED QUALITY — do not repeat these, beat them:\n" + history
            )
        sections.append(f"REVISION GOAL\n{bias}")
        if mutation == "append":
            sections.append(
                "Return only ONE new rule to append after the current text. Do not repeat, "
                "summarize, or rewrite the current text. No preamble, no explanation, no "
                "markdown fences. Do not mention the output format or the schema — a fixed "
                "block owns that. The rule must decide one measured failure above."
            )
        else:
            sections.append(
                "Return only the rewritten block. No preamble, no explanation, no markdown "
                "fences. Do not mention the output format or the schema — a fixed block owns "
                "that. Write rules that decide the failing cases above, not encouragement."
            )
        user = "\n\n".join(sections)
        prompt = CompiledPrompt(
            technique_id="optimizer.meta",
            stage="propose",
            messages=[
                Message(
                    role="system",
                    content=(
                        "You rewrite prompt instructions. You are terse, concrete, and you only "
                        "add rules that a measured failure justifies."
                    ),
                ),
                Message(role="user", content=user),
            ],
            generation_options={"temperature": 0.9},
        )
        model = self.engine_model or task.model
        result = await self.engine_provider.generate(prompt, model, timeout_seconds)
        return _strip_fences(result.content)

    async def _evaluate(
        self,
        candidate: Candidate,
        task: TaskProfile,
        technique: TechniqueSpec,
        dataset: list[BenchmarkExample],
        repeats: int,
        timeout_seconds: float,
        dataset_name: str,
    ) -> BenchmarkReport:
        patched = candidate.overlay.apply(technique)
        merged = dataset
        if candidate.overlay.exemplars:
            merged = [
                item.model_copy(
                    update={"exemplars": [*item.exemplars, *candidate.overlay.exemplars]}
                )
                for item in dataset
            ]
        return await self.runner.run(
            dataset=merged,
            task=task,
            technique=patched,
            repeats=repeats,
            timeout_seconds=timeout_seconds,
            dataset_name=dataset_name,
        )


# --------------------------------------------------------------------------- #
# scoring
# --------------------------------------------------------------------------- #


def _rescore(candidates: list[Candidate], priorities) -> None:
    """Score every candidate against the best measured cost in the population."""
    cards = [item.train for item in candidates if item.train is not None]
    scored = [item for item in candidates if item.train is not None]
    if not cards:
        return
    best_latency = min(card.mean_latency_seconds for card in cards) or 1e-9
    best_tokens = min(card.mean_total_tokens for card in cards) or 1e-9
    for item in scored:
        card = item.train
        assert card is not None
        latency_efficiency = min(1.0, best_latency / max(card.mean_latency_seconds, 1e-9))
        token_efficiency = min(1.0, best_tokens / max(card.mean_total_tokens, 1e-9))
        item.score = round(
            priorities.quality * card.quality
            + priorities.reliability * card.reliability
            + priorities.latency * latency_efficiency
            + priorities.token_cost * token_efficiency,
            4,
        )


def _report_calls(report: BenchmarkReport) -> int:
    """Count actual strategy calls represented by a benchmark report."""
    return sum(run.calls for run in report.runs)


def select_parents(ranked: list[Candidate], beam_width: int) -> list[Candidate]:
    """The beam: best by weighted score, plus the best by raw quality.

    A greedy loop that only ever mutates the weighted-score leader throws away
    the candidate that actually answers more examples correctly but pays for it
    in tokens. On a task where quality is what you are chasing, that candidate is
    the more promising parent, so it stays in the beam.
    """
    if not ranked:
        return []
    beam_width = max(1, beam_width)
    scored = [item for item in ranked if item.train is not None]
    if not scored:
        return ranked[:1]

    parents: list[Candidate] = [scored[0]]
    by_quality = sorted(scored, key=lambda item: item.train.quality, reverse=True)  # type: ignore[union-attr]
    for candidate in by_quality:
        if len(parents) >= beam_width:
            break
        if candidate.id not in {item.id for item in parents}:
            parents.append(candidate)
    # Any remaining slots go to the next best by weighted score.
    for candidate in scored:
        if len(parents) >= beam_width:
            break
        if candidate.id not in {item.id for item in parents}:
            parents.append(candidate)
    return parents


def pareto_front(candidates: list[Candidate]) -> list[Candidate]:
    """Candidates not beaten on every axis at once (quality, reliability, cost, speed)."""
    scored = [item for item in candidates if item.train is not None]
    front: list[Candidate] = []
    for item in scored:
        card = item.train
        assert card is not None
        dominated = False
        for other in scored:
            if other is item or other.train is None:
                continue
            rival = other.train
            better_or_equal = (
                rival.quality >= card.quality
                and rival.reliability >= card.reliability
                and rival.mean_total_tokens <= card.mean_total_tokens
                and rival.mean_latency_seconds <= card.mean_latency_seconds
            )
            strictly_better = (
                rival.quality > card.quality
                or rival.reliability > card.reliability
                or rival.mean_total_tokens < card.mean_total_tokens
                or rival.mean_latency_seconds < card.mean_latency_seconds
            )
            if better_or_equal and strictly_better:
                dominated = True
                break
        if not dominated:
            front.append(item)
    return front


def export_technique(technique: TechniqueSpec, candidate: Candidate) -> dict[str, Any]:
    """Emit the winner as a registry-ready technique file."""
    payload = technique.model_dump(mode="json")
    payload["id"] = f"{technique.id}.optimized"
    payload["title"] = f"{technique.title} (optimized)"
    payload["version"] = "1.0.0"
    payload["evidence_level"] = "benchmarked"
    payload["description"] = (
        f"{technique.description} Instructions optimized against measured results "
        f"(origin: {candidate.origin})."
    )
    if candidate.train:
        payload["characteristics"] = {
            **payload["characteristics"],
            "quality": round(candidate.train.quality, 4),
            "reliability": round(candidate.train.reliability, 4),
        }
    return payload


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _split(
    dataset: list[BenchmarkExample], validation_ratio: float
) -> tuple[list[BenchmarkExample], list[BenchmarkExample]]:
    """Deterministic interleaved split, so reruns compare like with like."""
    ordered = sorted(dataset, key=lambda item: item.id)
    hold_out = max(1, round(len(ordered) * validation_ratio))
    step = max(1, len(ordered) // hold_out)
    validation = ordered[::step][:hold_out]
    validation_ids = {item.id for item in validation}
    train = [item for item in ordered if item.id not in validation_ids]
    if not train:  # tiny datasets: keep one example on each side
        train, validation = ordered[:1], ordered[1:]
    return train, validation


def _primary(grades: dict[str, float]) -> float:
    from prompt_selector.graders import QUALITY_PREFERENCE

    for name in QUALITY_PREFERENCE:
        if name in grades:
            return grades[name]
    return 0.0


def _failure_digest(
    report: BenchmarkReport | None,
    dataset: list[BenchmarkExample] | None = None,
    limit: int = 4,
) -> str:
    """Failing cases with the input, the gold answer and what came out.

    Without the gold answer a failure reads as "wrong content", from which no
    rule can be inferred — the proposer needs to see the difference to name it.
    """
    if report is None:
        return ""
    by_id = {item.id: item for item in dataset or []}
    ranked = sorted(report.runs, key=lambda run: _primary(run.grades))
    lines: list[str] = []
    for run in ranked[:limit]:
        if _primary(run.grades) >= 0.999 and not run.schema_errors and not run.error:
            continue
        detail = run.error or "; ".join(run.schema_errors) or "wrong content"
        example = by_id.get(run.example_id)
        tags = f" [{', '.join(example.tags)}]" if example and example.tags else ""
        block = [f"- {run.example_id}{tags}: score {_primary(run.grades):.2f} ({detail})"]
        if example:
            block.append(f"  input:    {_clip(example.input, 160)}")
            if example.expected is not None:
                block.append(
                    f"  expected: {_clip(json.dumps(example.expected, ensure_ascii=False))}"
                )
        block.append(f"  produced: {_clip(run.output)}")
        lines.append("\n".join(block))
    return "\n".join(lines)


def technique_digest(technique: TechniqueSpec, target: str) -> str:
    """The prompt skeleton the block lives in.

    Without this the proposer is editing a paragraph in a vacuum: it does not
    know a schema block already owns the output format, so it spends its rewrite
    restating it — words that change nothing and cost tokens.
    """
    lines: list[str] = []
    owns_contract = {"contract_native", "contract_embedded", "fields"}
    for index, block in enumerate(technique.recipe.blocks, 1):
        title = block.title or block.name
        if block.name == target:
            role = "← YOU ARE REWRITING THIS ONE"
        elif block.name in owns_contract:
            role = "fixed — already states the required output format"
        elif block.name == "input":
            role = "fixed — carries the task input"
        else:
            role = "fixed"
        condition = "" if block.when.value == "always" else f", only when {block.when.value}"
        lines.append(f"  {index}. {title} ({block.name}{condition}) — {role}")
    return "\n".join(lines)


def tag_digest(report: BenchmarkReport | None, dataset: list[BenchmarkExample]) -> str:
    """Which kinds of case are failing, worst first.

    A mean score per tag is the closest thing to "here is the distinction you
    keep getting wrong" that can be computed without a judge model.
    """
    if report is None:
        return ""
    tags_by_id = {item.id: item.tags for item in dataset}
    buckets: dict[str, list[float]] = {}
    for run in report.runs:
        score = _primary(run.grades)
        for tag in tags_by_id.get(run.example_id, []) or ["untagged"]:
            buckets.setdefault(tag, []).append(score)
    if not buckets:
        return ""
    ranked = sorted(buckets.items(), key=lambda item: sum(item[1]) / len(item[1]))
    lines = [
        f'  "{tag}" — {sum(scores) / len(scores):.2f} mean score over {len(scores)} example(s)'
        for tag, scores in ranked
        if sum(scores) / len(scores) < 0.999
    ]
    return "\n".join(lines[:6])


def history_digest(candidates, target: str, limit: int = 4) -> str:
    """Instructions already measured, with their scores, so the proposer can
    climb rather than rediscover. This is the OPRO signal MIPRO also uses."""
    scored = []
    for item in candidates:
        if item.train is None:
            continue
        body = item.overlay.block_bodies.get(target, "")
        appended = item.overlay.block_appends.get(target, "")
        mutation = "\n".join(part for part in (body.rstrip(), appended.rstrip()) if part)
        if mutation:
            scored.append((item.train.quality, mutation))
    if not scored:
        return ""
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return "\n".join(f"  [{score:.2f}] {_clip(body, 180)}" for score, body in scored[:limit])


def _clip(text: str, limit: int = 220) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[:limit] + "…"


def _strip_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        body = stripped.split("\n", 1)[-1]
        if body.rstrip().endswith("```"):
            body = body.rstrip()[:-3]
        return body.strip()
    return stripped


def dumps(result: OptimizationResult) -> str:
    return json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False)


def export_front(result: OptimizationResult, technique: TechniqueSpec) -> dict[str, dict[str, Any]]:
    """Every Pareto candidate as a registry-ready technique, keyed by candidate id.

    The scalarized winner is not always the one to keep: a candidate can be both
    more accurate and cheaper and still lose the weighted score.
    """
    return {
        candidate.id: export_technique(candidate.overlay.apply(technique), candidate)
        for candidate in result.pareto_front
    }


def diverse_sample(items: list[Any], key, k: int) -> list[Any]:
    """Pick k items that are unlike each other, greedily (Auto-CoT's idea).

    Auto-CoT clusters questions with sentence embeddings and takes one per
    cluster, so the demonstrations cover different kinds of case. There is no
    embedding model here, so distance is lexical: the share of content words two
    inputs do *not* share. That is a weaker signal than embeddings but it still
    beats "take the three shortest", which reliably picks three near-duplicates.
    """
    if k <= 0 or not items:
        return []
    if len(items) <= k:
        return list(items)

    words = {id(item): _content_words(key(item)) for item in items}
    # Start from the shortest input: a short correct demonstration is the cheapest
    # to carry and the least likely to confuse.
    chosen = [min(items, key=lambda item: len(key(item)))]
    while len(chosen) < k:
        remaining = [item for item in items if item not in chosen]
        if not remaining:
            break
        chosen.append(
            max(
                remaining,
                key=lambda item: min(
                    _jaccard_distance(words[id(item)], words[id(picked)]) for picked in chosen
                ),
            )
        )
    return chosen


def _content_words(text: str) -> set[str]:
    import re

    return {word for word in re.findall(r"[\w']{3,}", text.lower())}


def _jaccard_distance(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 0.0
    union = left | right
    return 1.0 - (len(left & right) / len(union) if union else 0.0)
