"""Deterministic rendering of technique recipes into prompt text.

Recipes are data, never code: a block body may only reference placeholders from
a closed vocabulary, and may only be gated by a :class:`BlockCondition`.
Anything else is a registry error, surfaced by ``validate-registry``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from prompt_playoff.domain import (
    BlockCondition,
    Capability,
    Exemplar,
    PromptBlock,
    TaskProfile,
    TechniqueSpec,
)


class TemplateError(ValueError):
    pass


#: Placeholders filled in at execution time, not compile time. They survive
#: rendering verbatim so a compiled prompt still shows where runtime data lands.
DEFERRED_PLACEHOLDERS = frozenset(
    {"previous", "chunk", "partials", "candidates", "errors", "draft", "path", "result"}
)

#: Placeholders every recipe may use.
BASE_PLACEHOLDERS = frozenset(
    {
        "input",
        "task_type",
        "domain",
        "complexity",
        "output_contract",
        "instructions",
        "schema_json",
        "schema_fields",
        "exemplars",
        "model_id",
        "max_calls",
        "max_output_tokens",
        "validators",
    }
)

_TOKEN = re.compile(r"\{\{|\}\}|\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


@dataclass
class RenderContext:
    values: dict[str, str] = field(default_factory=dict)
    flags: dict[BlockCondition, bool] = field(default_factory=dict)
    deferred: set[str] = field(default_factory=set)

    def allows(self, condition: BlockCondition) -> bool:
        return self.flags.get(condition, False)


def build_context(
    task: TaskProfile,
    technique: TechniqueSpec,
    user_input: str,
    response_schema: dict[str, Any] | None = None,
    variables: dict[str, str] | None = None,
    exemplars: list[Exemplar] | None = None,
) -> RenderContext:
    native_schema = response_schema is not None and (
        Capability.structured_output in task.model.capabilities
    )
    exemplars = list(exemplars or []) or list(technique.recipe.exemplars)

    values: dict[str, str] = {
        "input": user_input.strip(),
        "task_type": task.task_type.value,
        "domain": task.domain or "general",
        "complexity": task.complexity,
        "output_contract": task.output_contract,
        "instructions": _numbered(technique.recipe.instructions),
        "schema_json": json.dumps(response_schema, ensure_ascii=False, indent=2)
        if response_schema
        else "",
        "schema_fields": _schema_fields(response_schema),
        "exemplars": render_exemplars(exemplars),
        "model_id": task.model.model_id,
        "max_calls": str(task.constraints.max_calls),
        "max_output_tokens": str(task.constraints.max_output_tokens or "unbounded"),
        "validators": ", ".join(technique.recipe.validators) or "none",
    }
    values.update(technique.recipe.variables)
    values.update(variables or {})

    flags = {
        BlockCondition.always: True,
        BlockCondition.has_schema: response_schema is not None,
        BlockCondition.native_schema: native_schema,
        BlockCondition.embedded_schema: response_schema is not None and not native_schema,
        BlockCondition.strict_json: task.constraints.strict_json,
        BlockCondition.free_text: not task.constraints.strict_json,
        BlockCondition.has_exemplars: bool(exemplars),
        BlockCondition.supplied_material: task.constraints.supplied_material,
        BlockCondition.topic_only: not task.constraints.supplied_material,
        BlockCondition.tools_allowed: task.constraints.tools_allowed,
        BlockCondition.requires_validation: task.constraints.requires_validation,
        BlockCondition.has_domain: bool(task.domain),
        BlockCondition.reasoning_control: Capability.reasoning_control in task.model.capabilities,
    }
    return RenderContext(values=values, flags=flags)


def render_text(template: str, context: RenderContext) -> str:
    """Substitute placeholders. Unknown names are a registry error."""

    def replace(match: re.Match[str]) -> str:
        token = match.group(0)
        if token == "{{":
            return "{"
        if token == "}}":
            return "}"
        name = match.group(1)
        if name in DEFERRED_PLACEHOLDERS:
            context.deferred.add(name)
            return token
        if name not in context.values:
            raise TemplateError(f"Unknown placeholder {{{name}}}")
        return context.values[name]

    return _TOKEN.sub(replace, template)


def render_block(block: PromptBlock, context: RenderContext) -> str | None:
    if not context.allows(block.when):
        return None
    body = render_text(block.body, context).strip()
    if not body:
        return None
    if block.title:
        return f"{block.title}\n{body}"
    return body


def render_blocks(blocks: list[PromptBlock], context: RenderContext) -> str:
    rendered = [render_block(block, context) for block in blocks]
    return "\n\n".join(section for section in rendered if section).strip()


def render_exemplars(exemplars: list[Exemplar]) -> str:
    parts: list[str] = []
    for index, exemplar in enumerate(exemplars, 1):
        chunk = (
            f"Example {index}\nInput:\n{exemplar.input.strip()}\nOutput:\n{exemplar.output.strip()}"
        )
        if exemplar.note:
            chunk += f"\nWhy: {exemplar.note.strip()}"
        parts.append(chunk)
    return "\n\n".join(parts)


def placeholders_in(template: str) -> set[str]:
    found: set[str] = set()
    for match in _TOKEN.finditer(template):
        if match.group(1):
            found.add(match.group(1))
    return found


def known_placeholders(technique: TechniqueSpec) -> set[str]:
    return set(BASE_PLACEHOLDERS | DEFERRED_PLACEHOLDERS) | set(technique.recipe.variables)


def _numbered(items: list[str]) -> str:
    return "\n".join(f"{index}. {text}" for index, text in enumerate(items, 1))


def _schema_fields(schema: dict[str, Any] | None) -> str:
    if not schema or schema.get("type") != "object":
        return ""
    required = set(schema.get("required", []))
    lines: list[str] = []
    for name, definition in (schema.get("properties") or {}).items():
        kind = definition.get("type", "any")
        if kind == "array":
            item_type = (definition.get("items") or {}).get("type", "any")
            kind = f"array<{item_type}>"
        flag = "required" if name in required else "optional"
        description = definition.get("description")
        line = f"- {name}: {kind} ({flag})"
        if description:
            line += f" — {description}"
        lines.append(line)
    return "\n".join(lines)
