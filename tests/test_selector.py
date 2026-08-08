from prompt_selector.domain import (
    Capability,
    Constraints,
    ModelClass,
    ModelProfile,
    Priorities,
    TaskProfile,
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
