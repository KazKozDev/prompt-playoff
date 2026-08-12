"""Execution strategies: how a compiled program turns into real provider calls.

A technique picks a strategy by name in YAML and passes it parameters. Adding a
technique that reuses an existing strategy needs no Python at all; adding a new
strategy is one class plus one decorator.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from collections.abc import Callable
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from prompt_playoff.domain import (
    CallRecord,
    CompiledProgram,
    CompiledPrompt,
    ExecutionTrace,
    Message,
    ModelProfile,
    TaskProfile,
)
from prompt_playoff.providers import ModelProvider


class StrategyError(RuntimeError):
    pass


class NoParams(BaseModel):
    model_config = {"extra": "forbid"}


class Strategy:
    """Base class. Subclasses declare a name, a params model, and execute()."""

    name: ClassVar[str] = ""
    Params: ClassVar[type[BaseModel]] = NoParams
    #: Stage names the strategy requires the recipe to define.
    required_stages: ClassVar[tuple[str, ...]] = ()

    def parse_params(self, raw: dict[str, Any]) -> BaseModel:
        return self.Params.model_validate(raw)

    def expected_calls(self, params: BaseModel, stage_count: int) -> int:
        return max(1, stage_count)

    def notes(self, params: BaseModel) -> list[str]:
        return []

    async def execute(
        self,
        program: CompiledProgram,
        task: TaskProfile,
        provider: ModelProvider,
        timeout_seconds: float,
    ) -> ExecutionTrace:  # pragma: no cover - abstract
        raise NotImplementedError


_STRATEGIES: dict[str, Strategy] = {}


def register_strategy(cls: type[Strategy]) -> type[Strategy]:
    if not cls.name:
        raise StrategyError(f"{cls.__name__} must declare a name")
    _STRATEGIES[cls.name] = cls()
    return cls


def get_strategy(name: str) -> Strategy:
    try:
        return _STRATEGIES[name]
    except KeyError as exc:
        known = ", ".join(sorted(_STRATEGIES))
        raise StrategyError(f"Unknown execution strategy {name!r}. Known: {known}") from exc


def strategy_names() -> list[str]:
    return sorted(_STRATEGIES)


# --------------------------------------------------------------------------- #
# shared helpers
# --------------------------------------------------------------------------- #


def normalize_usage(usage: dict[str, Any]) -> tuple[int, int]:
    """Map provider-specific usage onto (prompt_tokens, completion_tokens)."""
    prompt = usage.get("prompt_eval_count") or usage.get("prompt_tokens") or 0
    completion = usage.get("eval_count") or usage.get("completion_tokens") or 0
    return int(prompt), int(completion)


def substitute(prompt: CompiledPrompt, replacements: dict[str, str]) -> CompiledPrompt:
    """Fill runtime placeholders left intact at compile time."""
    if not replacements:
        return prompt
    updated = prompt.model_copy(deep=True)
    for message in updated.messages:
        for name, value in replacements.items():
            message.content = message.content.replace(f"{{{name}}}", value)
    return updated


async def call_once(
    provider: ModelProvider,
    prompt: CompiledPrompt,
    model: ModelProfile,
    timeout_seconds: float,
    index: int,
) -> CallRecord:
    started = time.perf_counter()
    result = await provider.generate(prompt, model, timeout_seconds)
    latency = time.perf_counter() - started
    prompt_tokens, completion_tokens = normalize_usage(result.usage)
    return CallRecord(
        stage=prompt.stage,
        index=index,
        content=result.content,
        latency_seconds=round(latency, 4),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )


def stage_named(program: CompiledProgram, name: str) -> CompiledPrompt:
    for stage in program.stages:
        if stage.stage == name:
            return stage
    raise StrategyError(f"Technique {program.technique_id} has no stage {name!r}")


def canonical(text: str) -> str:
    """Normalize an answer so equivalent outputs vote together."""
    stripped = text.strip()
    try:
        return json.dumps(json.loads(stripped), sort_keys=True, ensure_ascii=False)
    except (json.JSONDecodeError, TypeError):
        return " ".join(stripped.lower().split())


# --------------------------------------------------------------------------- #
# aggregators
# --------------------------------------------------------------------------- #

Aggregator = Callable[[list[str]], tuple[str, dict[str, Any]]]
_AGGREGATORS: dict[str, Aggregator] = {}


def register_aggregator(name: str) -> Callable[[Aggregator], Aggregator]:
    def wrapper(func: Aggregator) -> Aggregator:
        _AGGREGATORS[name] = func
        return func

    return wrapper


def get_aggregator(name: str) -> Aggregator:
    try:
        return _AGGREGATORS[name]
    except KeyError as exc:
        known = ", ".join(sorted(_AGGREGATORS))
        raise StrategyError(f"Unknown aggregator {name!r}. Known: {known}") from exc


def aggregator_names() -> list[str]:
    return sorted(_AGGREGATORS)


@register_aggregator("majority_vote")
def majority_vote(candidates: list[str]) -> tuple[str, dict[str, Any]]:
    """Pick the most repeated normalized answer; agreement is a measured number."""
    if not candidates:
        return "", {"agreement": 0.0, "samples": 0}
    keys = [canonical(item) for item in candidates]
    counts = Counter(keys)
    winner_key, votes = counts.most_common(1)[0]
    winner = next(
        candidate for candidate, key in zip(candidates, keys, strict=True) if key == winner_key
    )
    return winner, {
        "agreement": round(votes / len(candidates), 4),
        "samples": len(candidates),
        "distinct_answers": len(counts),
        "votes": votes,
    }


@register_aggregator("json_field_vote")
def json_field_vote(candidates: list[str]) -> tuple[str, dict[str, Any]]:
    """Vote per top-level JSON field; falls back to majority vote on non-JSON."""
    parsed: list[dict[str, Any]] = []
    for candidate in candidates:
        try:
            value = json.loads(candidate.strip())
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            parsed.append(value)
    if not parsed:
        return majority_vote(candidates)

    keys = sorted({key for item in parsed for key in item})
    merged: dict[str, Any] = {}
    field_agreement: dict[str, float] = {}
    for key in keys:
        values = [
            json.dumps(item[key], sort_keys=True, ensure_ascii=False)
            for item in parsed
            if key in item
        ]
        counts = Counter(values)
        winner_key, votes = counts.most_common(1)[0]
        merged[key] = json.loads(winner_key)
        field_agreement[key] = round(votes / len(parsed), 4)
    agreement = (
        round(sum(field_agreement.values()) / len(field_agreement), 4) if field_agreement else 0.0
    )
    return json.dumps(merged, ensure_ascii=False), {
        "agreement": agreement,
        "samples": len(candidates),
        "parsed_samples": len(parsed),
        "field_agreement": field_agreement,
    }


# --------------------------------------------------------------------------- #
# strategies
# --------------------------------------------------------------------------- #


@register_strategy
class SingleCall(Strategy):
    name = "single"

    def expected_calls(self, params: BaseModel, stage_count: int) -> int:
        return 1

    async def execute(
        self,
        program: CompiledProgram,
        task: TaskProfile,
        provider: ModelProvider,
        timeout_seconds: float,
    ) -> ExecutionTrace:
        record = await call_once(provider, program.main, task.model, timeout_seconds, 0)
        return ExecutionTrace(
            technique_id=program.technique_id,
            strategy=self.name,
            output=record.content,
            calls=[record],
        )


class SelfConsistencyParams(BaseModel):
    model_config = {"extra": "forbid"}

    samples: int = Field(default=3, ge=2, le=10)
    temperature: float = Field(default=0.8, ge=0, le=2)
    aggregator: str = "majority_vote"


@register_strategy
class SelfConsistency(Strategy):
    name = "self_consistency"
    Params = SelfConsistencyParams

    def expected_calls(self, params: BaseModel, stage_count: int) -> int:
        assert isinstance(params, SelfConsistencyParams)
        return params.samples

    def notes(self, params: BaseModel) -> list[str]:
        assert isinstance(params, SelfConsistencyParams)
        return [
            f"Runs {params.samples} independent samples at temperature "
            f"{params.temperature} and aggregates with {params.aggregator}.",
            "Reported agreement is measured across those samples, not assumed.",
        ]

    async def execute(
        self,
        program: CompiledProgram,
        task: TaskProfile,
        provider: ModelProvider,
        timeout_seconds: float,
    ) -> ExecutionTrace:
        params = self.parse_params(program.strategy_params)
        assert isinstance(params, SelfConsistencyParams)
        base = program.main
        calls: list[CallRecord] = []
        for index in range(params.samples):
            sample = base.model_copy(deep=True)
            sample.generation_options = {
                **sample.generation_options,
                "temperature": params.temperature,
                "seed": index,
            }
            calls.append(await call_once(provider, sample, task.model, timeout_seconds, index))

        output, aggregation = get_aggregator(params.aggregator)([call.content for call in calls])
        aggregation["aggregator"] = params.aggregator
        return ExecutionTrace(
            technique_id=program.technique_id,
            strategy=self.name,
            output=output,
            calls=calls,
            aggregation=aggregation,
        )


class MultiStageParams(BaseModel):
    model_config = {"extra": "forbid"}

    #: Stage whose output is the final answer. Defaults to the last stage.
    final_stage: str | None = None


@register_strategy
class MultiStage(Strategy):
    name = "multi_stage"
    Params = MultiStageParams

    def expected_calls(self, params: BaseModel, stage_count: int) -> int:
        return max(1, stage_count)

    def notes(self, params: BaseModel) -> list[str]:
        return ["Each stage receives the previous stage output through {previous}."]

    async def execute(
        self,
        program: CompiledProgram,
        task: TaskProfile,
        provider: ModelProvider,
        timeout_seconds: float,
    ) -> ExecutionTrace:
        params = self.parse_params(program.strategy_params)
        assert isinstance(params, MultiStageParams)
        calls: list[CallRecord] = []
        outputs: dict[str, str] = {}
        previous = ""
        for index, stage in enumerate(program.stages):
            filled = substitute(
                stage, {"previous": previous, "draft": outputs.get("draft", previous)}
            )
            record = await call_once(provider, filled, task.model, timeout_seconds, index)
            calls.append(record)
            previous = record.content
            outputs[stage.stage] = record.content

        final = params.final_stage or program.stages[-1].stage
        if final not in outputs:
            raise StrategyError(f"final_stage {final!r} did not produce output")
        return ExecutionTrace(
            technique_id=program.technique_id,
            strategy=self.name,
            output=outputs[final],
            calls=calls,
            aggregation={"stages": [stage.stage for stage in program.stages], "final_stage": final},
        )


class MapReduceParams(BaseModel):
    model_config = {"extra": "forbid"}

    chunk_chars: int = Field(default=3000, ge=200, le=100_000)
    overlap_chars: int = Field(default=0, ge=0, le=2000)
    max_chunks: int = Field(default=12, ge=1, le=100)


@register_strategy
class MapReduce(Strategy):
    name = "map_reduce"
    Params = MapReduceParams
    required_stages = ("map", "reduce")

    def expected_calls(self, params: BaseModel, stage_count: int) -> int:
        return 2

    def notes(self, params: BaseModel) -> list[str]:
        assert isinstance(params, MapReduceParams)
        return [
            f"Input is split into ~{params.chunk_chars}-character chunks; the map stage "
            "runs once per chunk and the reduce stage merges the partial results.",
            "Call count therefore scales with input length.",
        ]

    async def execute(
        self,
        program: CompiledProgram,
        task: TaskProfile,
        provider: ModelProvider,
        timeout_seconds: float,
    ) -> ExecutionTrace:
        params = self.parse_params(program.strategy_params)
        assert isinstance(params, MapReduceParams)
        map_stage = stage_named(program, "map")
        reduce_stage = stage_named(program, "reduce")

        chunks = split_chunks(program.source_input, params.chunk_chars, params.overlap_chars)
        chunks = chunks[: params.max_chunks]

        calls: list[CallRecord] = []
        partials: list[str] = []
        for index, chunk in enumerate(chunks):
            filled = substitute(map_stage, {"chunk": chunk})
            record = await call_once(provider, filled, task.model, timeout_seconds, index)
            calls.append(record)
            partials.append(f"Partial {index + 1}:\n{record.content}")

        joined = "\n\n".join(partials)
        reduce_filled = substitute(reduce_stage, {"partials": joined})
        reduce_record = await call_once(
            provider, reduce_filled, task.model, timeout_seconds, len(chunks)
        )
        calls.append(reduce_record)

        return ExecutionTrace(
            technique_id=program.technique_id,
            strategy=self.name,
            output=reduce_record.content,
            calls=calls,
            aggregation={"chunks": len(chunks), "chunk_chars": params.chunk_chars},
        )


class ToolLoopParams(BaseModel):
    model_config = {"extra": "forbid"}

    max_iterations: int = Field(default=4, ge=1, le=12)


@register_strategy
class ToolLoop(Strategy):
    """A real ReAct loop: call, execute the requested tools, feed observations back."""

    name = "tool_loop"
    Params = ToolLoopParams

    def expected_calls(self, params: BaseModel, stage_count: int) -> int:
        assert isinstance(params, ToolLoopParams)
        return params.max_iterations

    def notes(self, params: BaseModel) -> list[str]:
        assert isinstance(params, ToolLoopParams)
        return [
            f"Iterates up to {params.max_iterations} times: the model may request tools, the "
            "registered handler executes them, and the observation is appended as a tool message.",
            "Only tools present in the registry can be called; with an empty registry the loop "
            "collapses to a single call.",
        ]

    async def execute(
        self,
        program: CompiledProgram,
        task: TaskProfile,
        provider: ModelProvider,
        timeout_seconds: float,
    ) -> ExecutionTrace:
        from prompt_playoff.tools import DEFAULT_REGISTRY

        params = self.parse_params(program.strategy_params)
        assert isinstance(params, ToolLoopParams)

        working = program.main.model_copy(deep=True)
        calls: list[CallRecord] = []
        observations: list[dict[str, Any]] = []

        for iteration in range(params.max_iterations):
            started = time.perf_counter()
            result = await provider.generate(working, task.model, timeout_seconds)
            latency = time.perf_counter() - started
            prompt_tokens, completion_tokens = normalize_usage(result.usage)
            calls.append(
                CallRecord(
                    stage=working.stage,
                    index=iteration,
                    content=result.content,
                    latency_seconds=round(latency, 4),
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                )
            )
            if not result.tool_calls:
                break

            working.messages.append(Message(role="assistant", content=result.content or ""))
            for tool_call in result.tool_calls:
                function = tool_call.get("function", tool_call)
                name = function.get("name", "")
                arguments = function.get("arguments", {})
                observation = DEFAULT_REGISTRY.call(name, arguments)
                observations.append(
                    {"tool": name, "arguments": arguments, "observation": observation}
                )
                working.messages.append(Message(role="tool", content=observation))

        return ExecutionTrace(
            technique_id=program.technique_id,
            strategy=self.name,
            output=calls[-1].content if calls else "",
            calls=calls,
            aggregation={
                "iterations": len(calls),
                "tool_calls": len(observations),
                "observations": observations[:10],
            },
        )


def split_chunks(text: str, chunk_chars: int, overlap_chars: int = 0) -> list[str]:
    """Split on paragraph boundaries, packing up to chunk_chars per chunk."""
    text = text.strip()
    if not text:
        return [""]
    if len(text) <= chunk_chars:
        return [text]

    paragraphs = [item for item in re.split(r"\n\s*\n", text) if item.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) > chunk_chars and current:
            chunks.append(current)
            tail = current[-overlap_chars:] if overlap_chars else ""
            current = f"{tail}\n\n{paragraph}".strip() if tail else paragraph
        else:
            current = candidate
    if current:
        chunks.append(current)

    expanded: list[str] = []
    for chunk in chunks:
        if len(chunk) <= chunk_chars:
            expanded.append(chunk)
            continue
        step = chunk_chars - overlap_chars or chunk_chars
        for start in range(0, len(chunk), step):
            piece = chunk[start : start + chunk_chars]
            if piece.strip():
                expanded.append(piece)
    return expanded


class TreeSearchParams(BaseModel):
    model_config = {"extra": "forbid"}

    depth: int = Field(default=2, ge=1, le=4)
    #: Partial solutions kept after each round of scoring.
    beam: int = Field(default=2, ge=1, le=4)
    breadth: int = Field(default=3, ge=2, le=6)
    temperature: float = Field(default=0.8, ge=0, le=2)


@register_strategy
class TreeSearch(Strategy):
    """Tree of Thoughts: expand several partial solutions, score them, keep the best.

    The published version explores one thought per call. That is ruinous at this
    scale, so each expansion asks for `breadth` alternatives in a single call and
    one scoring call ranks the survivors. The shape — expand, evaluate, prune,
    repeat — is preserved; the call count is not proportional to the branching
    factor.
    """

    name = "tree_search"
    Params = TreeSearchParams
    required_stages = ("expand", "evaluate", "answer")

    def expected_calls(self, params: BaseModel, stage_count: int) -> int:
        assert isinstance(params, TreeSearchParams)
        # The first round starts from a single empty path, so only later rounds
        # pay for the full beam.
        return 2 + (params.depth - 1) * (params.beam + 1) + 1

    def notes(self, params: BaseModel) -> list[str]:
        assert isinstance(params, TreeSearchParams)
        return [
            f"Explores {params.breadth} alternatives per step, keeps the best {params.beam} "
            f"for {params.depth} rounds, then answers — "
            f"{self.expected_calls(params, 0)} calls in total.",
            "The scores come from the model ranking its own branches; they are not measured.",
        ]

    async def execute(
        self,
        program: CompiledProgram,
        task: TaskProfile,
        provider: ModelProvider,
        timeout_seconds: float,
    ) -> ExecutionTrace:
        params = self.parse_params(program.strategy_params)
        assert isinstance(params, TreeSearchParams)
        expand = stage_named(program, "expand")
        evaluate = stage_named(program, "evaluate")
        answer = stage_named(program, "answer")

        calls: list[CallRecord] = []
        index = 0
        paths: list[str] = ["(nothing yet)"]
        history: list[dict[str, Any]] = []

        for round_index in range(params.depth):
            proposals: list[str] = []
            for path in paths[: params.beam]:
                filled = substitute(expand, {"path": path, "previous": path})
                filled.generation_options = {
                    **filled.generation_options,
                    "temperature": params.temperature,
                    "seed": index,
                }
                record = await call_once(provider, filled, task.model, timeout_seconds, index)
                calls.append(record)
                index += 1
                # One call returns several alternatives; keeping the reply whole
                # would collapse the tree into a single chain.
                proposals += split_options(record.content, params.breadth)

            numbered = "\n\n".join(f"Option {n}:\n{text}" for n, text in enumerate(proposals, 1))
            ranked = substitute(evaluate, {"candidates": numbered, "previous": numbered})
            record = await call_once(provider, ranked, task.model, timeout_seconds, index)
            calls.append(record)
            index += 1

            paths = _order_by_ranking(proposals, record.content)
            history.append(
                {"round": round_index + 1, "expanded": len(proposals), "kept": params.beam}
            )

        best = paths[0] if paths else ""
        final = substitute(answer, {"path": best, "previous": best})
        record = await call_once(provider, final, task.model, timeout_seconds, index)
        calls.append(record)

        return ExecutionTrace(
            technique_id=program.technique_id,
            strategy=self.name,
            output=record.content,
            calls=calls,
            aggregation={"rounds": history, "beam": params.beam, "depth": params.depth},
        )


def split_options(reply: str, limit: int) -> list[str]:
    """Split a numbered list of alternatives into separate branches.

    Models number their options inconsistently ("1.", "1)", "Option 1:"), and a
    reply with no numbering at all is one branch, not zero.
    """
    parts = re.split(r"(?m)^\s*(?:option\s*)?\d+\s*[.):-]\s*", reply, flags=re.IGNORECASE)
    options = [part.strip() for part in parts if part.strip()]
    if not options:
        return [reply.strip()] if reply.strip() else []
    return options[:limit]


def _order_by_ranking(proposals: list[str], verdict: str) -> list[str]:
    """Read the ranking out of the scoring reply, falling back to the given order.

    A model asked to rank will often answer with prose around the numbers, so the
    digits are extracted and anything unmentioned keeps its original position
    rather than being dropped.
    """
    order: list[int] = []
    for token in re.findall(r"\d+", verdict):
        position = int(token) - 1
        if 0 <= position < len(proposals) and position not in order:
            order.append(position)
    order += [i for i in range(len(proposals)) if i not in order]
    return [proposals[i] for i in order]


class ProgramOfThoughtParams(BaseModel):
    model_config = {"extra": "forbid"}

    #: Retry once with the interpreter's error appended, which fixes most syntax slips.
    repair_attempts: int = Field(default=1, ge=0, le=2)


@register_strategy
class ProgramOfThought(Strategy):
    """Program of Thought: the model writes a program, we run it, it answers from the result.

    Execution goes through :mod:`prompt_playoff.sandbox`, a restricted AST
    interpreter — not ``exec``. A model-written program reaches arithmetic,
    collections and a whitelist of builtins, and nothing else.
    """

    name = "program_of_thought"
    Params = ProgramOfThoughtParams
    required_stages = ("code", "answer")

    def expected_calls(self, params: BaseModel, stage_count: int) -> int:
        assert isinstance(params, ProgramOfThoughtParams)
        return 2 + params.repair_attempts

    def notes(self, params: BaseModel) -> list[str]:
        return [
            "The generated program runs in a restricted interpreter: no imports, no attribute "
            "access, no file or network access, and a step budget.",
            "A program that fails to run is reported to the answer stage as an error rather "
            "than silently ignored.",
        ]

    async def execute(
        self,
        program: CompiledProgram,
        task: TaskProfile,
        provider: ModelProvider,
        timeout_seconds: float,
    ) -> ExecutionTrace:
        from prompt_playoff.sandbox import run_program

        params = self.parse_params(program.strategy_params)
        assert isinstance(params, ProgramOfThoughtParams)
        code_stage = stage_named(program, "code")
        answer_stage = stage_named(program, "answer")

        calls: list[CallRecord] = []
        index = 0
        source = ""
        result = None

        for attempt in range(params.repair_attempts + 1):
            filled = code_stage
            if attempt:
                filled = substitute(
                    code_stage,
                    {"errors": f"The previous program failed: {result.error}\n\n{source}"},
                )
            record = await call_once(provider, filled, task.model, timeout_seconds, index)
            calls.append(record)
            index += 1
            source = record.content
            result = run_program(source)
            if result.ok:
                break

        assert result is not None
        final = substitute(
            answer_stage,
            {"result": result.render(), "previous": result.render(), "errors": result.error or ""},
        )
        record = await call_once(provider, final, task.model, timeout_seconds, index)
        calls.append(record)

        return ExecutionTrace(
            technique_id=program.technique_id,
            strategy=self.name,
            output=record.content,
            calls=calls,
            aggregation={
                "program_ran": result.ok,
                "program_error": result.error,
                "computed": result.render()[:200],
                "attempts": index - 1,
            },
        )
