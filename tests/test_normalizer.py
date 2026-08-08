from prompt_selector.domain import Capability, ModelProfile, TaskType
from prompt_selector.normalizer import normalize_description


def test_normalizer_infers_extraction_and_json() -> None:
    model = ModelProfile(capabilities={Capability.structured_output, Capability.system_messages})
    result = normalize_description(
        "Extract entities into strict JSON. Reliability matters most.", model
    )
    assert result.task_type == TaskType.structured_extraction
    assert result.constraints.strict_json is True
    assert result.priorities.reliability == 0.5
