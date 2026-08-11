from collections import Counter

from prompt_selector.domain import (
    Capability,
    Constraints,
    ModelClass,
    ModelProfile,
    Priorities,
    TaskProfile,
    TaskShape,
    TaskType,
)
from prompt_selector.registry import Registry
from prompt_selector.selector import Selector


def extraction_profile() -> TaskProfile:
    return TaskProfile(
        task_type=TaskType.structured_extraction,
        output_contract="json_schema",
        priorities=Priorities(quality=0.3, reliability=0.5, latency=0.1, token_cost=0.1),
        constraints=Constraints(
            local_only=True,
            max_calls=2,
            tools_allowed=False,
            strict_json=True,
            requires_validation=True,
        ),
        model=ModelProfile(
            provider="ollama",
            model_id="test-model",
            model_class=ModelClass.medium,
            local=True,
            capabilities={Capability.structured_output, Capability.system_messages},
        ),
    )


def test_schema_first_wins_for_structured_extraction() -> None:
    result = Selector(Registry.load()).select(extraction_profile())
    assert result.recommendations[0].technique_id == "structured.schema-first"
    assert result.recommendations[0].score > 0.8


def test_react_is_rejected_when_tools_are_disabled() -> None:
    result = Selector(Registry.load()).select(extraction_profile())
    rejected = {item.technique_id: item for item in result.rejected}
    assert "agents.react" in rejected
    assert any("tools are disabled" in reason for reason in rejected["agents.react"].reasons)


def test_max_calls_rejects_multicall_techniques() -> None:
    profile = extraction_profile().model_copy(
        update={"constraints": extraction_profile().constraints.model_copy(update={"max_calls": 1})}
    )
    result = Selector(Registry.load()).select(profile)
    rejected_ids = {item.technique_id for item in result.rejected}
    assert "structured.few-shot-repair" in rejected_ids
    assert "reasoning.self-consistency" in rejected_ids


def research_profile(**constraints) -> TaskProfile:
    return TaskProfile(
        task_type=TaskType.research,
        priorities=Priorities(quality=0.35, reliability=0.35, latency=0.15, token_cost=0.15),
        constraints=Constraints(local_only=True, requires_validation=False, **constraints),
        model=ModelProfile(
            provider="ollama",
            model_id="test-model",
            model_class=ModelClass.medium,
            local=True,
            capabilities={Capability.system_messages, Capability.tool_calling},
        ),
    )


def test_evidence_first_is_rejected_when_the_material_must_be_gathered() -> None:
    result = Selector(Registry.load()).select(research_profile(retrieval_required=True))

    rejected = {item.technique_id: item for item in result.rejected}
    assert "grounding.evidence-first" in rejected
    assert any(
        "gather the material" in reason for reason in rejected["grounding.evidence-first"].reasons
    )
    assert "grounding.evidence-first" not in {item.technique_id for item in result.recommendations}


def test_evidence_first_still_wins_when_the_evidence_is_supplied() -> None:
    result = Selector(Registry.load()).select(research_profile(tools_allowed=True))

    assert result.recommendations[0].technique_id == "grounding.evidence-first"


def test_retrieval_task_prefers_a_tool_loop() -> None:
    result = Selector(Registry.load()).select(
        research_profile(retrieval_required=True, tools_allowed=True)
    )

    assert result.recommendations[0].technique_id == "agents.react"
    assert result.recommendations[0].breakdown.retrieval_fit == 1.0


def test_retrieval_task_warns_when_nothing_can_retrieve() -> None:
    result = Selector(Registry.load()).select(research_profile(retrieval_required=True))

    assert any("no recommended technique can retrieve it" in item for item in result.warnings)


def coding_profile(*shape: TaskShape) -> TaskProfile:
    return TaskProfile(
        task_type=TaskType.coding,
        shape=set(shape),
        priorities=Priorities(),
        constraints=Constraints(local_only=True, requires_validation=False),
        model=ModelProfile(
            provider="ollama",
            model_id="test-model",
            model_class=ModelClass.medium,
            local=True,
            capabilities={Capability.system_messages},
        ),
    )


def test_one_task_type_gets_different_techniques_for_different_requests() -> None:
    selector = Selector(Registry.load())

    stepped = selector.select(coding_profile(TaskShape.multi_step, TaskShape.high_stakes))
    checkable = selector.select(coding_profile(TaskShape.verifiable, TaskShape.exact_format))

    assert stepped.recommendations[0].technique_id != checkable.recommendations[0].technique_id
    assert stepped.recommendations[0].technique_id == "reasoning.plan-execute"
    assert checkable.recommendations[0].technique_id == "coding.tests-first"


def test_the_winner_is_not_decided_in_the_fourth_decimal() -> None:
    """A recipe that covers both traits must win by a margin a person can see.

    Two recipes built for the same single trait may still finish close together —
    that is an honest tie. What must not happen is the whole field landing inside
    one percent, which is what made a single technique win every coding request.
    """
    top = (
        Selector(Registry.load())
        .select(coding_profile(TaskShape.multi_step, TaskShape.high_stakes))
        .recommendations
    )

    assert top[0].score - top[1].score > 0.05


def test_a_rare_trait_outranks_a_common_one() -> None:
    registry = Registry.load()
    claims = Counter(
        trait for technique in registry.techniques.values() for trait in technique.suits
    )
    assert claims[TaskShape.has_examples] < claims[TaskShape.verifiable]

    result = Selector(registry).select(
        TaskProfile(
            task_type=TaskType.structured_extraction,
            shape={TaskShape.has_examples, TaskShape.verifiable},
            constraints=Constraints(local_only=True, requires_validation=False),
            model=ModelProfile(local=True, capabilities={Capability.system_messages}),
        )
    )
    scores = {item.technique_id: item.breakdown.shape_fit for item in result.recommendations}
    winner = result.recommendations[0]
    assert TaskShape.has_examples in registry.technique(winner.technique_id).suits
    assert scores[winner.technique_id] > 0.5


def test_an_extra_call_costs_more_when_the_task_has_no_steps() -> None:
    selector = Selector(Registry.load())

    flat = selector.select(coding_profile(TaskShape.verifiable), limit=20)
    stepped = selector.select(coding_profile(TaskShape.verifiable, TaskShape.multi_step), limit=20)

    def penalty(result, technique_id: str) -> float:
        return next(
            item.breakdown.penalties
            for item in result.recommendations
            if item.technique_id == technique_id
        )

    assert penalty(flat, "reasoning.plan-execute") > penalty(stepped, "reasoning.plan-execute")


def test_a_request_with_no_declared_shape_stays_neutral() -> None:
    result = Selector(Registry.load()).select(coding_profile())

    assert {item.breakdown.shape_fit for item in result.recommendations} == {0.5}


def topic_profile(task_type: TaskType = TaskType.summarization) -> TaskProfile:
    return TaskProfile(
        task_type=task_type,
        constraints=Constraints(
            local_only=True, requires_validation=False, supplied_material=False
        ),
        model=ModelProfile(local=True, capabilities={Capability.system_messages}),
    )


def test_a_topic_gets_no_technique_that_works_on_supplied_material() -> None:
    """The failure this closes: a prompt telling the model to quote what nobody gave it."""
    result = Selector(Registry.load()).select(topic_profile())

    rejected = {item.technique_id for item in result.rejected}
    assert {
        "grounding.evidence-first",
        "grounding.chain-of-note",
        "context.map-reduce",
        "reasoning.system2-attention",
        "reasoning.re-reading",
    } <= rejected
    for item in result.recommendations:
        assert not Registry.load().technique(item.technique_id).requires_supplied_evidence


def test_the_same_techniques_come_back_once_material_is_supplied() -> None:
    supplied = topic_profile().model_copy(
        update={
            "constraints": Constraints(
                local_only=True, requires_validation=False, supplied_material=True
            )
        }
    )

    result = Selector(Registry.load()).select(supplied)

    rejected = {item.technique_id for item in result.rejected}
    assert (
        not {
            "grounding.evidence-first",
            "grounding.chain-of-note",
            "reasoning.system2-attention",
            "reasoning.re-reading",
        }
        & rejected
    )


def test_a_task_that_needs_material_says_so_when_none_is_given() -> None:
    result = Selector(Registry.load()).select(topic_profile(TaskType.translation))

    assert any("names a topic without supplying it" in item for item in result.warnings)
