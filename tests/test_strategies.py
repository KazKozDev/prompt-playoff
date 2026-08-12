import pytest
from conftest import FakeProvider, ToolCallingProvider

from prompt_playoff.compiler import PromptCompiler
from prompt_playoff.domain import TaskType
from prompt_playoff.strategies import (
    get_strategy,
    json_field_vote,
    majority_vote,
    split_chunks,
    strategy_names,
)
from prompt_playoff.tools import DEFAULT_REGISTRY


@pytest.mark.asyncio
async def test_single_strategy_makes_exactly_one_call(extraction_task, entity_schema, registry):
    program = PromptCompiler().compile(
        extraction_task, registry.technique("structured.schema-first"), "Input", entity_schema
    )
    provider = FakeProvider()
    trace = await get_strategy("single").execute(program, extraction_task, provider, 30)
    assert len(provider.calls) == 1
    assert len(trace.calls) == 1
    assert trace.total_tokens == 120


@pytest.mark.asyncio
async def test_multi_stage_feeds_the_previous_output_forward(
    extraction_task, entity_schema, registry
):
    program = PromptCompiler().compile(
        extraction_task, registry.technique("structured.few-shot-repair"), "Input", entity_schema
    )
    provider = FakeProvider(
        responses=['{"people": ["Draft"], "places": []}', '{"people": ["Fixed"], "places": []}']
    )
    trace = await get_strategy("multi_stage").execute(program, extraction_task, provider, 30)

    assert len(provider.calls) == 2
    repair_prompt = provider.calls[1].messages[1].content
    assert '{"people": ["Draft"], "places": []}' in repair_prompt
    assert "{previous}" not in repair_prompt
    assert trace.output == '{"people": ["Fixed"], "places": []}'


@pytest.mark.asyncio
async def test_self_consistency_runs_n_samples_and_measures_agreement(
    extraction_task, entity_schema, registry
):
    program = PromptCompiler().compile(
        extraction_task, registry.technique("reasoning.self-consistency"), "Input", entity_schema
    )
    provider = FakeProvider(responses=['{"a": 1}', '{"a": 2}', '{"a": 1}'])
    trace = await get_strategy("self_consistency").execute(program, extraction_task, provider, 30)

    assert len(provider.calls) == 3
    assert trace.aggregation["agreement"] == pytest.approx(2 / 3, abs=1e-3)
    assert trace.output == '{"a": 1}'
    assert {call.generation_options["seed"] for call in provider.calls} == {0, 1, 2}


@pytest.mark.asyncio
async def test_map_reduce_calls_once_per_chunk_plus_a_reduce(extraction_task, registry):
    task = extraction_task.model_copy(deep=True)
    task.task_type = TaskType.summarization
    long_input = "\n\n".join(f"Paragraph {index}. " + "x" * 1500 for index in range(4))
    program = PromptCompiler().compile(task, registry.technique("context.map-reduce"), long_input)

    provider = FakeProvider(responses=["partial"])
    trace = await get_strategy("map_reduce").execute(program, task, provider, 30)

    chunks = trace.aggregation["chunks"]
    assert chunks >= 2
    assert len(provider.calls) == chunks + 1
    reduce_prompt = provider.calls[-1].messages[1].content
    assert "Partial 1:" in reduce_prompt
    assert "{partials}" not in reduce_prompt


@pytest.mark.asyncio
async def test_tool_loop_executes_the_requested_tool(extraction_task, registry):
    task = extraction_task.model_copy(deep=True)
    task.task_type = TaskType.agents
    task.constraints.tools_allowed = True
    program = PromptCompiler().compile(task, registry.technique("agents.react"), "What is 6*7?")

    provider = ToolCallingProvider()
    trace = await get_strategy("tool_loop").execute(program, task, provider, 30)

    assert len(provider.calls) == 2
    assert trace.aggregation["tool_calls"] == 1
    observation = trace.aggregation["observations"][0]["observation"]
    assert '"result": 42.0' in observation
    assert trace.output == "42"


def test_default_tool_registry_word_count_is_deterministic():
    assert "word_count" in DEFAULT_REGISTRY.names()
    assert DEFAULT_REGISTRY.call("word_count", {"text": "red fox crosses quiet field."}) == (
        '{"count": 5}'
    )
    assert DEFAULT_REGISTRY.call("word_count", {"text": "don't split hyphen-like words"}) == (
        '{"count": 4}'
    )


def test_majority_vote_normalizes_equivalent_json():
    winner, meta = majority_vote(['{"a":1,"b":2}', '{"b":2,"a":1}', '{"a":9}'])
    assert meta["agreement"] == pytest.approx(2 / 3, abs=1e-3)
    assert meta["distinct_answers"] == 2
    assert "a" in winner


def test_json_field_vote_merges_per_field():
    winner, meta = json_field_vote(['{"a":1,"b":1}', '{"a":1,"b":2}', '{"a":3,"b":2}'])
    import json as _json

    assert _json.loads(winner) == {"a": 1, "b": 2}
    assert meta["field_agreement"] == {
        "a": pytest.approx(2 / 3, abs=1e-3),
        "b": pytest.approx(2 / 3, abs=1e-3),
    }


def test_split_chunks_respects_the_limit():
    text = "\n\n".join("word " * 200 for _ in range(6))
    chunks = split_chunks(text, chunk_chars=1200, overlap_chars=100)
    assert len(chunks) > 1
    assert all(len(chunk) <= 1200 for chunk in chunks)


def test_every_declared_strategy_is_registered(registry):
    for technique in registry.techniques.values():
        assert technique.execution.strategy in strategy_names(), technique.id


@pytest.mark.asyncio
async def test_tree_search_expands_ranks_and_answers(extraction_task, entity_schema, registry):
    program = PromptCompiler().compile(
        extraction_task, registry.technique("reasoning.tree-of-thought"), "Input", entity_schema
    )
    # Round 1 starts from one path (2 calls); round 2 expands the beam (3); then answer.
    assert program.expected_calls == 6

    # Ranking replies "2, 1", so the second option must lead the next round.
    provider = FakeProvider(
        responses=["1. branch A\n2. branch B", "2, 1", "next", "next", "1", "final"]
    )
    trace = await get_strategy("tree_search").execute(program, extraction_task, provider, 30)

    assert len(provider.calls) == 6
    rank_prompt = provider.calls[1].messages[1].content
    assert "Option 1:" in rank_prompt and "Option 2:" in rank_prompt
    assert "{candidates}" not in rank_prompt
    assert trace.aggregation["depth"] == 2
    assert trace.output == "final"


def test_ranking_survives_a_chatty_reply():
    """A model asked for numbers often wraps them in prose; unranked options are kept."""
    from prompt_playoff.strategies import _order_by_ranking

    options = ["first", "second", "third"]
    assert _order_by_ranking(options, "I think 3, then 1, then 2.") == ["third", "first", "second"]
    # Only one number mentioned: the rest hold their original order.
    assert _order_by_ranking(options, "Option 2 looks best.") == ["second", "first", "third"]
    assert _order_by_ranking(options, "no idea") == options


@pytest.mark.asyncio
async def test_program_of_thought_runs_the_program(extraction_task, entity_schema, registry):
    program = PromptCompiler().compile(
        extraction_task, registry.technique("reasoning.program-of-thought"), "Input", entity_schema
    )
    provider = FakeProvider(
        responses=["```python\nanswer = sum([1, 2, 3])\n```", '{"people": [], "places": []}']
    )
    trace = await get_strategy("program_of_thought").execute(program, extraction_task, provider, 30)

    assert trace.aggregation["program_ran"] is True
    assert trace.aggregation["computed"] == "6"
    # The computed value has to reach the answer stage.
    assert "6" in provider.calls[-1].messages[1].content
    assert "{result}" not in provider.calls[-1].messages[1].content


@pytest.mark.asyncio
async def test_a_broken_program_is_reported_not_hidden(extraction_task, entity_schema, registry):
    program = PromptCompiler().compile(
        extraction_task, registry.technique("reasoning.program-of-thought"), "Input", entity_schema
    )
    provider = FakeProvider(responses=["```python\nanswer = (\n```"])
    trace = await get_strategy("program_of_thought").execute(program, extraction_task, provider, 30)

    assert trace.aggregation["program_ran"] is False
    assert "syntax error" in trace.aggregation["program_error"]
    # One code call, one repair attempt, one answer call.
    assert len(provider.calls) == 3
