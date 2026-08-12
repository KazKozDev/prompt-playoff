from __future__ import annotations

import json
from typing import Any

import pytest

from prompt_playoff.domain import (
    Capability,
    CompiledPrompt,
    Constraints,
    ModelClass,
    ModelProfile,
    ModelResult,
    Priorities,
    TaskProfile,
    TaskType,
)
from prompt_playoff.registry import Registry

ENTITY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "people": {"type": "array", "items": {"type": "string"}},
        "places": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["people", "places"],
    "additionalProperties": False,
}


class FakeProvider:
    """Deterministic stand-in for a model, so evals are testable without one."""

    def __init__(self, responses: list[str] | None = None, usage: dict | None = None) -> None:
        self.responses = responses or ['{"people": ["Mara"], "places": ["Veyr"]}']
        self.usage = usage or {"prompt_eval_count": 100, "eval_count": 20}
        self.calls: list[CompiledPrompt] = []

    async def generate(
        self,
        prompt: CompiledPrompt,
        model: ModelProfile,
        timeout_seconds: float = 120,
    ) -> ModelResult:
        self.calls.append(prompt.model_copy(deep=True))
        content = self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]
        return ModelResult(content=content, usage=dict(self.usage))


class ToolCallingProvider:
    """Answers with one tool call, then a final answer."""

    def __init__(self) -> None:
        self.calls: list[CompiledPrompt] = []

    async def generate(
        self,
        prompt: CompiledPrompt,
        model: ModelProfile,
        timeout_seconds: float = 120,
    ) -> ModelResult:
        self.calls.append(prompt.model_copy(deep=True))
        if len(self.calls) == 1:
            return ModelResult(
                content="",
                tool_calls=[
                    {
                        "function": {
                            "name": "calculator",
                            "arguments": json.dumps({"expression": "6*7"}),
                        }
                    }
                ],
                usage={"prompt_eval_count": 50, "eval_count": 10},
            )
        return ModelResult(content="42", usage={"prompt_eval_count": 60, "eval_count": 5})


@pytest.fixture(scope="session")
def registry() -> Registry:
    return Registry.load()


@pytest.fixture
def extraction_task() -> TaskProfile:
    return TaskProfile(
        task_type=TaskType.structured_extraction,
        output_contract="json_schema",
        priorities=Priorities(quality=0.3, reliability=0.5, latency=0.1, token_cost=0.1),
        constraints=Constraints(
            local_only=True,
            max_calls=3,
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


@pytest.fixture
def entity_schema() -> dict[str, Any]:
    return json.loads(json.dumps(ENTITY_SCHEMA))


@pytest.fixture(autouse=True)
def isolated_measurements(tmp_path, monkeypatch):
    """Keep the suite independent of whatever has been benchmarked locally."""
    monkeypatch.setenv("PROMPT_PLAYOFF_MEASUREMENTS", str(tmp_path / "measurements.json"))
    monkeypatch.setenv("PROMPT_PLAYOFF_ENGINE_CACHE", str(tmp_path / "engine-cache.json"))
    monkeypatch.setenv("PROMPT_PLAYOFF_JOBS_PATH", str(tmp_path / "jobs.json"))
