from __future__ import annotations

from typing import Any

from prompt_selector.domain import (
    BlockCondition,
    Capability,
    CompiledProgram,
    CompiledPrompt,
    Exemplar,
    Message,
    PromptBlock,
    StageSpec,
    TaskProfile,
    TechniqueSpec,
)
from prompt_selector.strategies import get_strategy
from prompt_selector.templating import RenderContext, build_context, render_blocks, render_text
from prompt_selector.tools import DEFAULT_REGISTRY, ToolRegistry


class CompileError(ValueError):
    pass


#: Used when a technique predates the block format: keeps old recipes renderable.
LEGACY_BLOCKS = [
    PromptBlock(name="task", title="TASK TYPE", body="{task_type}"),
    PromptBlock(name="instructions", title="INSTRUCTIONS", body="{instructions}"),
    PromptBlock(name="input", title="INPUT", body="{input}"),
]


class PromptCompiler:
    """Turns a task plus a technique into the concrete calls that technique implies."""

    def __init__(self, tools: ToolRegistry | None = None) -> None:
        self.tools = tools if tools is not None else DEFAULT_REGISTRY

    def compile(
        self,
        task: TaskProfile,
        technique: TechniqueSpec,
        user_input: str,
        response_schema: dict[str, Any] | None = None,
        variables: dict[str, str] | None = None,
        exemplars: list[Exemplar] | None = None,
    ) -> CompiledProgram:
        context = build_context(task, technique, user_input, response_schema, variables, exemplars)
        blocks = technique.recipe.blocks or LEGACY_BLOCKS
        by_name = {block.name: block for block in blocks}

        strategy = get_strategy(technique.execution.strategy)
        try:
            params = strategy.parse_params(technique.execution.params)
        except Exception as exc:  # pydantic validation error
            raise CompileError(
                f"{technique.id}: invalid params for strategy {strategy.name!r}: {exc}"
            ) from exc

        missing = [
            name
            for name in strategy.required_stages
            if name not in {stage.name for stage in technique.execution.stages}
        ]
        if missing:
            raise CompileError(
                f"{technique.id}: strategy {strategy.name!r} requires stages: {', '.join(missing)}"
            )

        stage_specs = technique.execution.stages or [
            StageSpec(name="main", blocks=[block.name for block in blocks])
        ]

        native_schema = response_schema if self._schema_is_native(task, response_schema) else None
        validators = self._validators(task, technique, response_schema)
        tools = (
            self.tools.declarations()
            if technique.tools_required and task.constraints.tools_allowed
            else []
        )

        stages: list[CompiledPrompt] = []
        for spec in stage_specs:
            selected = [by_name[name] for name in spec.blocks] if spec.blocks else blocks
            stage_context = RenderContext(
                values=dict(context.values), flags=dict(context.flags), deferred=set()
            )
            body = render_blocks(selected, stage_context)
            system = render_text(spec.system or technique.recipe.system, stage_context).strip()
            options = self._generation_options(task, spec.temperature)

            stages.append(
                CompiledPrompt(
                    technique_id=technique.id,
                    stage=spec.name,
                    messages=[
                        Message(role="system", content=system),
                        Message(role="user", content=body),
                    ],
                    response_schema=native_schema if spec.carries_schema else None,
                    tools=tools,
                    generation_options=options,
                    validators=validators,
                    fallback=technique.recipe.fallback,
                    think=self._think(task),
                    deferred_placeholders=sorted(stage_context.deferred),
                )
            )

        notes = strategy.notes(params)
        wants_exemplars = any(block.when is BlockCondition.has_exemplars for block in blocks)
        if wants_exemplars and not context.allows(BlockCondition.has_exemplars):
            notes.append(
                "This technique is built around demonstrations, but none were supplied, so the "
                "example block is empty. Pass exemplars to use it as intended."
            )
        if context.allows(BlockCondition.has_exemplars) and not wants_exemplars:
            notes.append(
                "Demonstrations were supplied but this technique declares no block with "
                "`when: has_exemplars`, so they do not reach the model. Few-shot bootstrapping "
                "only helps techniques that have an example block."
            )
        if response_schema and native_schema is None:
            notes.append(
                "The model declares no native structured output, so the schema is embedded "
                "in the prompt and validated after the call."
            )

        return CompiledProgram(
            technique_id=technique.id,
            technique_title=technique.title,
            technique_version=technique.version,
            strategy=strategy.name,
            strategy_params=params.model_dump(),
            stages=stages,
            response_schema=native_schema,
            validators=validators,
            fallback=technique.recipe.fallback,
            expected_calls=strategy.expected_calls(params, len(stages)),
            notes=notes,
            source_input=user_input,
        )

    @staticmethod
    def _schema_is_native(task: TaskProfile, response_schema: dict[str, Any] | None) -> bool:
        return bool(response_schema) and Capability.structured_output in task.model.capabilities

    @staticmethod
    def _generation_options(task: TaskProfile, temperature: float | None) -> dict[str, Any]:
        if temperature is None:
            temperature = 0.7 if task.task_type.value == "creative_writing" else 0.1
        options: dict[str, Any] = {
            "temperature": temperature,
            "num_ctx": min(task.model.context_window, 32768),
        }
        if task.constraints.max_output_tokens:
            options["num_predict"] = task.constraints.max_output_tokens
        return options

    @staticmethod
    def _think(task: TaskProfile) -> bool | None:
        if Capability.reasoning_control not in task.model.capabilities:
            return None
        return task.task_type.value in {"coding", "research", "agents"}

    @staticmethod
    def _validators(
        task: TaskProfile,
        technique: TechniqueSpec,
        response_schema: dict[str, Any] | None,
    ) -> list[str]:
        validators = list(dict.fromkeys(technique.recipe.validators))
        if task.constraints.strict_json and "json_validity" not in validators:
            validators.append("json_validity")
        if response_schema and "json_schema" not in validators:
            validators.append("json_schema")
        return validators
