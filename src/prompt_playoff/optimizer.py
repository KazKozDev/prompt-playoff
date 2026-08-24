"""Automatic prompt optimization driven by measured numbers.

The loop is the one DSPy (MIPRO/GEPA), OPRO and EvoPrompt converged on, adapted
to this project's registry:

    seed candidates -> benchmark each on a train split -> score with the task's
    own priorities over measured quality, reliability, latency and tokens ->
    reflect on the worst failures to propose better instructions -> repeat ->
    verify the winner on a held-out split.

Nothing is scored by an LLM judge and nothing is estimated: every number comes
from :mod:`prompt_playoff.evals`, so "the prompt got better" means it got
better on data you can inspect.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

from prompt_playoff.compiler import PromptCompiler
from prompt_playoff.domain import (
    CompiledProgram,
    CompiledPrompt,
    Exemplar,
    Message,
    ModelProfile,
    TaskProfile,
    TechniqueSpec,
)
from prompt_playoff.evals import (
    BenchmarkExample,
    BenchmarkReport,
    BenchmarkRunner,
    Scorecard,
    overlap_scored_references,
)
from prompt_playoff.graders import (
    REFERENCE_OVERLAP_GRADERS,
    chance_level_is_useless,
    describe,
    token_f1_chance_level,
)
from prompt_playoff.providers import ModelProvider, ProviderError


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
    #: In authored mode the candidate is not an edit to a recipe but a whole
    #: prompt: the text the person is holding, or a rewrite of it. The overlay
    #: cannot express that — it patches recipe blocks, and an authored prompt has
    #: no blocks left to patch, only rendered messages.
    program: CompiledProgram | None = None
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
    #: The recorded run this result became, when `record` was on. It is what a
    #: release registered from this prompt points back to.
    experiment_id: str | None = None
    #: The winning prompt itself, when the search rewrote a prompt rather than a
    #: recipe. Adopting it is a copy, not a recompile: the text measured here is
    #: exactly the text that would be adopted, which is not true in recipe mode.
    winner_program: dict[str, Any] | None = None


def _improvement(baseline: Scorecard, winner: Scorecard) -> dict[str, float]:
    return {
        "quality": round(winner.quality - baseline.quality, 4),
        "reliability": round(winner.reliability - baseline.reliability, 4),
        "mean_total_tokens": round(winner.mean_total_tokens - baseline.mean_total_tokens, 2),
        "mean_latency_seconds": round(
            winner.mean_latency_seconds - baseline.mean_latency_seconds, 4
        ),
    }


def _discard_note(failures: list[str]) -> list[str]:
    """Why proposals did not make it, counted rather than listed one by one."""
    from collections import Counter

    if not failures:
        return []
    counts = Counter(failures)
    return [
        "Discarded proposals: "
        + "; ".join(f"{reason} ({count})" for reason, count in counts.most_common(4))
    ]


def _program_text(program: CompiledProgram) -> str:
    """Every word the model would be sent, normalized. The unit of "same prompt"."""
    return " ".join(
        " ".join(message.content.split()) for stage in program.stages for message in stage.messages
    )


def _input_slot(program: CompiledProgram) -> str | None:
    """Where an example's input goes, by the same rule `authored_for` applies.

    A rewrite that loses this is not a worse prompt, it is an unrunnable one:
    there is nowhere to put the row, so it cannot be scored at all.
    """
    written = "\n".join(m.content for stage in program.stages for m in stage.messages)
    if "{input}" in written:
        return "{input}"
    source = program.source_input.strip()
    return source if source and source in written else None


def _with_message(
    program: CompiledProgram, stage_index: int, message: Message, content: str
) -> CompiledProgram:
    """The same program with one message replaced. Nothing else moves."""
    stages = []
    for index, stage in enumerate(program.stages):
        if index != stage_index:
            stages.append(stage)
            continue
        stages.append(
            stage.model_copy(
                update={
                    "messages": [
                        item.model_copy(update={"content": content}) if item is message else item
                        for item in stage.messages
                    ]
                }
            )
        )
    return program.model_copy(update={"stages": stages})


def with_demonstrations(program: CompiledProgram, pairs: list[Message]) -> CompiledProgram:
    """Worked turns before the real request, in the stage that carries the input.

    Before, not after: the last thing a model sees should be the request it is
    answering, so examples appended at the end teach the pattern and then bury
    it. They go into the stage holding the input slot, immediately ahead of its
    final user turn, and nothing already in the prompt is edited or moved.
    """
    target = next(
        (
            index
            for index, stage in enumerate(program.stages)
            if any(_slot_in(message.content, program) for message in stage.messages)
        ),
        0,
    )
    stages = []
    for index, stage in enumerate(program.stages):
        if index != target:
            stages.append(stage)
            continue
        messages = [item for item in stage.messages if not item.demo]
        cut = max(
            (i for i, item in enumerate(messages) if item.role == "user"),
            default=len(messages),
        )
        stages.append(
            stage.model_copy(update={"messages": [*messages[:cut], *pairs, *messages[cut:]]})
        )
    return program.model_copy(update={"stages": stages})


def without_demonstrations(program: CompiledProgram) -> CompiledProgram:
    """Take the worked turns back out. The prompt underneath was never edited."""
    return program.model_copy(
        update={
            "stages": [
                stage.model_copy(update={"messages": [m for m in stage.messages if not m.demo]})
                for stage in program.stages
            ]
        }
    )


def _slot_in(content: str, program: CompiledProgram) -> bool:
    if "{input}" in content:
        return True
    source = program.source_input.strip()
    return bool(source) and source in content


def _authored_history(candidates: list[Candidate]) -> str:
    """What has already been tried and what it scored, for prompts rather than blocks."""
    lines = []
    for candidate in candidates:
        if candidate.program is None or candidate.train is None:
            continue
        text = _program_text(candidate.program)
        lines.append(f"- quality {candidate.train.quality:.2f}: {text[:240]}")
    return "\n".join(lines[:6])


def _search_note(authored: CompiledProgram | None, backend: str) -> list[str]:
    """What the candidates are rewrites of. The native and DSPy paths differ.

    Only the native search rewrites an authored prompt. A DSPy backend searches
    the recipe's own instruction block whatever it is measured against, so a
    result from it must not be read as "the tool improved my wording".
    """
    if authored is None or backend == "native":
        return []
    return [
        f"{backend} searches the method's instruction block, not the prompt you supplied. "
        "The numbers are against your prompt; the candidates are not rewrites of it."
    ]


def _baseline_note(authored: CompiledProgram | None) -> list[str]:
    """Which prompt the deltas are against. Never left to be inferred."""
    if authored is None:
        return [
            "The baseline is the technique compiled fresh, not the prompt on your screen. "
            "Send that prompt with the run to have the deltas describe what you are holding."
        ]
    return [
        "The baseline is the prompt you authored, so every delta is against the text you "
        "have. The candidates are still written from the technique's own instruction blocks."
    ]


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


class UnmeasurableObjective(ValueError):
    """The search has no number worth maximising on this data."""


def refuse_unmeasurable(dataset: list[BenchmarkExample], *, allowed: bool = False) -> None:
    """Stop before the first model call when the objective cannot decide anything.

    A prompt search moves whatever number it is handed. Handed word overlap on
    rows whose answers already resemble each other, it will find a candidate
    that scores higher — reliably, every time — by drifting towards the shared
    wording of the corpus. That is not a slow way to improve a prompt; it is a
    fast way to make one worse while the number rises, and it costs an evening
    of calls to do it.

    So the search refuses, in the same voice the CI gate refuses a quality bar
    it cannot support, and for the same reason: reporting a result nobody can
    act on is worse than reporting none. Nothing here calls a model — the floor
    is computed from the rows — so the refusal is free and arrives first.
    """
    if allowed:
        return
    references = overlap_scored_references(dataset)
    chance = token_f1_chance_level(references)
    if not chance_level_is_useless(chance):
        return
    raise UnmeasurableObjective(
        f"These rows would be scored by token_f1, and an answer written for a different row "
        f"of this set already scores {chance:.2f} on it. A search against that number will "
        "raise it by echoing the wording every row shares, not by answering better. Give the "
        "rows requirements a rule can decide — contains_all, forbidden_content, length_limit, "
        "regex_match — and the search will have something worth maximising; or pass "
        "allow_noisy_objective to run anyway and read the result as drift."
    )


class PromptOptimizer:
    def __init__(
        self,
        provider: ModelProvider,
        engine_provider: ModelProvider | None = None,
        engine_model: ModelProfile | None = None,
        compiler: PromptCompiler | None = None,
        allow_noisy_objective: bool = False,
    ) -> None:
        self.provider = provider
        #: Run even when the number being maximised cannot decide anything. Off,
        #: because a search against such a number is not a slow way to improve a
        #: prompt — it is a fast way to make one worse while the score rises.
        self.allow_noisy_objective = allow_noisy_objective
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
        authored: CompiledProgram | None = None,
    ) -> OptimizationResult:
        """`authored` is the prompt the caller is holding, and it becomes the
        baseline. Without it the baseline is a fresh compile of the registry
        technique, so "improvement" is measured against a prompt the person has
        never seen — and a search that beat that compile could still be losing to
        the text on their screen. The candidates are still written from the
        technique: what changes is what they have to beat."""
        if len(dataset) < 2:
            raise ValueError("Optimization needs at least two examples to split")
        refuse_unmeasurable(dataset, allowed=self.allow_noisy_objective)
        started = time.perf_counter()
        train, validation = _split(dataset, validation_ratio)
        priorities = task.priorities.normalized()
        call_count = 0

        baseline = Candidate(
            id="baseline", technique_id=technique.id, origin="baseline", program=authored
        )
        population: list[Candidate] = [baseline]

        bootstrapped, bootstrap_calls = (
            await self._bootstrap_authored(
                task, technique, authored, train, timeout_seconds, dataset_name
            )
            if authored is not None
            else await self._bootstrap(task, technique, train, timeout_seconds, dataset_name)
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
                    candidate,
                    task,
                    technique,
                    train,
                    repeats,
                    timeout_seconds,
                    dataset_name,
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
                if authored is not None:
                    proposals += await self._propose_authored(
                        task,
                        parent,
                        reports.get(parent.id),
                        share,
                        timeout_seconds,
                        seen={
                            _program_text(item.program)
                            for item in [*evaluated.values(), *proposals]
                            if item.program is not None
                        },
                        train=train,
                        evaluated=list(evaluated.values()),
                    )
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

        if winner.program is not None:
            return self._authored_result(
                task=task,
                technique=technique,
                dataset_name=dataset_name,
                train=train,
                validation=validation,
                history=history,
                baseline=baseline,
                winner=winner,
                baseline_validation=baseline_validation,
                winner_validation=winner_validation,
                evaluated=list(evaluated.values()),
                priorities=priorities,
                call_count=call_count,
                started=started,
                authored=authored,
            )

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
            improvement=_improvement(baseline_validation, winner_validation),
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
            notes=[
                *_baseline_note(authored),
                *self._engine_note(task),
                *self._metric_note(winner_validation),
                *self._diagnosis(technique, winner),
            ],
        )

    def _authored_result(
        self,
        *,
        task: TaskProfile,
        technique: TechniqueSpec,
        dataset_name: str,
        train: list[BenchmarkExample],
        validation: list[BenchmarkExample],
        history: list[OptimizationRound],
        baseline: Candidate,
        winner: Candidate,
        baseline_validation: Scorecard,
        winner_validation: Scorecard,
        evaluated: list[Candidate],
        priorities: Any,
        call_count: int,
        started: float,
        authored: CompiledProgram | None,
    ) -> OptimizationResult:
        """The result of a search over prompts, where the winner is one.

        `exported_technique` is deliberately empty. The winner is not a recipe:
        writing the untouched technique into that field would offer a file that
        reproduces none of what was measured.
        """
        assert winner.program is not None
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
            improvement=_improvement(baseline_validation, winner_validation),
            pareto_front=pareto_front(evaluated),
            compiled_prompt={
                "strategy": winner.program.strategy,
                "expected_calls": winner.program.expected_calls,
                "stages": [
                    {
                        "stage": stage.stage,
                        "system": stage.messages[0].content,
                        "user": stage.messages[-1].content,
                    }
                    for stage in winner.program.stages
                ],
            },
            winner_program=winner.program.model_dump(mode="json"),
            exported_technique={},
            total_calls=call_count,
            elapsed_seconds=round(time.perf_counter() - started, 2),
            priorities=priorities.model_dump(),
            engine_model_id=(self.engine_model or task.model).model_id,
            engine_is_target=self.engine_model is None,
            notes=[
                *_baseline_note(authored),
                "The search rewrote the prompt itself rather than the recipe behind it, so "
                "the winning text is what was measured and adopting it copies it verbatim.",
                *self._engine_note(task),
                *self._metric_note(winner_validation),
                *_discard_note(self.proposal_failures),
            ],
        )

    def _metric_note(self, winner_validation: Scorecard) -> list[str]:
        """What the search was actually maximising, when that is not correctness.

        A prompt search moves whatever number it is given. On open-ended work
        that number is word overlap with one reference answer, and a candidate
        can win it by echoing the reference's wording rather than by answering
        better — which is how a search spends an evening of model calls to
        produce a worse prompt with a higher score. The result says so, and
        quotes the floor: a gain that sits inside what an answer to a different
        question already earns is not a gain anybody can act on.
        """
        card = winner_validation
        if card.quality_grader not in REFERENCE_OVERLAP_GRADERS:
            return []
        floor = (
            f" On these rows an answer written for a different row already scores "
            f"{card.quality_chance_level:.2f} on it, so a gain smaller than that gap is "
            "inside the metric's own noise."
            if card.quality_chance_level is not None
            else ""
        )
        return [
            f"The search maximised {card.quality_grader} — {describe(card.quality_grader)} — "
            "because these rows carry prose answers and nothing better applied. A candidate "
            "can win that by echoing the reference's wording rather than by answering better."
            + floor
            + " Give the rows requirements a rule can check (contains_all, forbidden_content, "
            "length_limit) and the search will have something worth maximising."
        ]

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

        from prompt_playoff.domain import BlockCondition

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

    async def _bootstrap_authored(
        self,
        task: TaskProfile,
        technique: TechniqueSpec,
        authored: CompiledProgram,
        train: list[BenchmarkExample],
        timeout_seconds: float,
        dataset_name: str,
    ) -> tuple[Candidate | None, int]:
        """The same bootstrap, for a prompt that has no exemplar block to fill.

        A recipe renders demonstrations into a block it owns. An authored prompt
        is finished text, so there is no such place — and guessing one inside
        somebody's prose means deciding where their instructions end, which
        cannot be read off free text without sometimes cutting a sentence in
        half. The demonstrations go beside the text instead of into it: worked
        turns before the real request, which is how a chat model expects to be
        shown an example anyway. The prompt itself is untouched, byte for byte.
        """
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
            authored=authored,
        )
        by_id = {item.id: item for item in graded}
        wins = [run for run in report.runs if _primary(run.grades) >= 0.999]
        if not wins:
            return None, _report_calls(report)
        wins = diverse_sample(
            wins,
            key=lambda run: by_id[run.example_id].input if run.example_id in by_id else "",
            k=3,
        )
        pairs: list[Message] = []
        for run in wins:
            if run.example_id not in by_id:
                continue
            pairs += [
                Message(role="user", content=by_id[run.example_id].input, demo=True),
                Message(role="assistant", content=run.output.strip(), demo=True),
            ]
        if not pairs:
            return None, _report_calls(report)
        return (
            Candidate(
                id="bootstrap-demos",
                technique_id=technique.id,
                origin="bootstrap",
                program=with_demonstrations(authored, pairs),
            ),
            _report_calls(report),
        )

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

    async def _propose_authored(
        self,
        task: TaskProfile,
        parent: Candidate,
        report: BenchmarkReport | None,
        count: int,
        timeout_seconds: float,
        seen: set[str],
        train: list[BenchmarkExample] | None,
        evaluated: list[Candidate] | None,
    ) -> list[Candidate]:
        """Rewrite the prompt itself, one stage's user message at a time.

        The block search cannot reach an authored prompt: by the time a person is
        holding one, the recipe's blocks have been rendered into messages and an
        engine model may have rewritten them, so patching a block changes nothing
        about the text on their screen. Here the message is the unit.

        Two things are enforced structurally rather than asked for. The rewrite
        must keep somewhere for an example's input to go, or the candidate cannot
        be measured at all; and it must be new, or the round is spent re-testing
        a known number. Everything else — including whether the rewrite kept the
        output contract — is settled by measurement, which is the only judge in
        this file.
        """
        assert parent.program is not None
        failures = _failure_digest(report, train)
        biases = mutation_biases(task)
        tags = tag_digest(report, train or [])
        history = _authored_history(evaluated or [])
        proposals: list[Candidate] = []
        for _ in range(count):
            stages = parent.program.stages
            index = self._proposal_seq % len(stages)
            bias = biases[self._proposal_seq % len(biases)]
            self._proposal_seq += 1
            stage = stages[index]
            spoken = next(
                (m for m in reversed(stage.messages) if m.role == "user"), stage.messages[-1]
            )
            try:
                rewritten = await self._ask_for_prompt(
                    task=task,
                    current=spoken.content,
                    bias=bias,
                    failures=failures,
                    scorecard=parent.train,
                    timeout_seconds=timeout_seconds,
                    slot=_input_slot(parent.program),
                    stage=stage.stage if len(stages) > 1 else "",
                    tags=tags,
                    history=history,
                )
            except ProviderError as exc:
                self.proposal_failures.append(f"proposer call failed: {exc}")
                continue
            if not rewritten:
                self.proposal_failures.append("proposer returned an empty prompt")
                continue
            if rewritten.strip() == spoken.content.strip():
                self.proposal_failures.append("proposer returned the original prompt")
                continue
            program = _with_message(parent.program, index, spoken, rewritten.strip())
            if _input_slot(program) is None:
                self.proposal_failures.append(
                    "proposer dropped the place an example's input goes, so the rewrite "
                    "could not be measured"
                )
                continue
            normalized = _program_text(program)
            if normalized in seen:
                self.proposal_failures.append("proposer repeated a prompt already measured")
                continue
            seen.add(normalized)
            self.proposals_accepted += 1
            proposals.append(
                Candidate(
                    id=f"{parent.id}+p{self._proposal_seq}",
                    technique_id=parent.technique_id,
                    origin=f"reflection:prompt:{parent.id}",
                    program=program,
                )
            )
        return proposals

    async def _ask_for_prompt(
        self,
        task: TaskProfile,
        current: str,
        bias: str,
        failures: str,
        scorecard: Scorecard | None,
        timeout_seconds: float,
        slot: str | None,
        stage: str = "",
        tags: str = "",
        history: str = "",
    ) -> str:
        """Ask for a rewrite of a whole message rather than of one block.

        The block prompt tells the proposer that a fixed block owns the output
        format and to never mention it. Here nothing else owns it: the contract
        is inside this text, so the instruction has to be the opposite — keep it,
        word for word if need be.
        """
        where = f" (stage {stage} of a multi-call prompt)" if stage else ""
        sections = [
            f"You are rewriting a complete prompt used for a {task.task_type.value} task"
            f"{where}. It is the whole instruction, not a fragment of one.",
            f"CURRENT PROMPT\n{current.strip()}",
        ]
        if slot:
            sections.append(
                f"MUST SURVIVE VERBATIM\n{slot}\n"
                "This is where each example's input is substituted. A rewrite without it "
                "cannot be run at all and will be discarded."
            )
        sections.append(
            "ALSO KEEP\nEvery instruction about the shape of the answer — the output format, "
            "the schema, the fields, what not to include. Nothing else in this prompt states "
            "them, so dropping them changes what the model returns."
        )
        if scorecard:
            sections.append(
                f"MEASURED PERFORMANCE\nquality {scorecard.quality:.2f}, "
                f"reliability {scorecard.reliability:.2f}, "
                f"{scorecard.mean_prompt_tokens:.0f} prompt tokens, "
                f"{scorecard.mean_latency_seconds:.2f}s per example."
            )
        if tags:
            sections.append(
                "WEAKEST CASE TYPES — analyst labels for KINDS OF INPUT, not fields in the "
                "output and not words that appear in the data. Never mention these labels in "
                "your rewrite; write the rule that decides the case instead.\n" + tags
            )
        sections.append(f"CONCRETE FAILURES\n{failures or 'None recorded.'}")
        if history:
            sections.append(
                "ALREADY TRIED, WITH MEASURED QUALITY — do not repeat these, beat them:\n" + history
            )
        sections.append(f"REVISION GOAL\n{bias}")
        sections.append(
            "Return only the rewritten prompt. No preamble, no explanation, no markdown "
            "fences. Write rules that decide the failing cases above, not encouragement."
        )
        prompt = CompiledPrompt(
            technique_id="optimizer.meta",
            stage="propose",
            messages=[
                Message(
                    role="system",
                    content=(
                        "You rewrite prompts. You are terse and concrete, you only add rules "
                        "that a measured failure justifies, and you never drop an instruction "
                        "you were told to keep."
                    ),
                ),
                Message(role="user", content="\n\n".join(sections)),
            ],
            generation_options={"temperature": 0.9},
        )
        model = self.engine_model or task.model
        result = await self.engine_provider.generate(prompt, model, timeout_seconds)
        return _strip_fences(result.content)

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
        authored: CompiledProgram | None = None,
    ) -> BenchmarkReport:
        if candidate.program is not None:
            return await self.runner.run(
                dataset=dataset,
                task=task,
                technique=technique,
                repeats=repeats,
                timeout_seconds=timeout_seconds,
                dataset_name=dataset_name,
                authored=candidate.program,
            )
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
            authored=authored,
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
    from prompt_playoff.graders import QUALITY_PREFERENCE

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
