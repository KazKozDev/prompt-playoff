from __future__ import annotations

from typing import Any

from prompt_selector.domain import (
    Capability,
    Constraints,
    ModelProfile,
    Priorities,
    TaskProfile,
    TaskType,
)

TASK_KEYWORDS: list[tuple[TaskType, tuple[str, ...]]] = [
    (TaskType.structured_extraction, ("extract", "извлеч", "json", "schema", "entity", "сущност")),
    (TaskType.translation, ("translate", "translation", "перевод")),
    (TaskType.coding, ("code", "coding", "program", "debug", "код", "программ")),
    (TaskType.research, ("research", "sources", "citation", "исслед", "источник")),
    (TaskType.classification, ("classify", "classification", "label", "классиф")),
    (TaskType.agents, ("agent", "tool calling", "react", "агент", "инструмент")),
    (TaskType.summarization, ("summar", "резюм", "сводк")),
    (TaskType.creative_writing, ("creative", "story", "novel", "write a book", "рассказ", "роман")),
]


def normalize_description(
    description: str,
    model: ModelProfile,
    overrides: dict[str, Any] | None = None,
) -> TaskProfile:
    text = description.lower()
    task_type = TaskType.summarization
    for candidate, keywords in TASK_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            task_type = candidate
            break

    strict_json = any(token in text for token in ("json", "schema", "structured", "строг"))
    tools_allowed = any(
        token in text for token in ("tool", "browser", "search", "инструмент", "браузер")
    )
    local_only = any(token in text for token in ("local", "ollama", "локальн")) or model.local

    quality, reliability, latency, token_cost = 0.35, 0.35, 0.15, 0.15
    if any(token in text for token in ("reliab", "stable", "стабиль", "надеж", "надёж")):
        reliability = 0.5
        quality, latency, token_cost = 0.3, 0.1, 0.1
    elif any(token in text for token in ("fast", "latency", "быстр", "скорост")):
        latency = 0.45
        quality, reliability, token_cost = 0.25, 0.2, 0.1
    elif any(token in text for token in ("cheap", "cost", "token", "дешев", "токен")):
        token_cost = 0.45
        quality, reliability, latency = 0.25, 0.2, 0.1

    profile = TaskProfile(
        task_type=task_type,
        output_contract="json_schema" if strict_json else "free_text",
        priorities=Priorities(
            quality=quality,
            reliability=reliability,
            latency=latency,
            token_cost=token_cost,
        ),
        constraints=Constraints(
            local_only=local_only,
            tools_allowed=tools_allowed,
            strict_json=strict_json,
            requires_validation=strict_json
            or task_type in {TaskType.coding, TaskType.structured_extraction},
        ),
        model=model,
    )
    if overrides:
        merged = profile.model_dump(mode="json")
        _deep_merge(merged, overrides)
        profile = TaskProfile.model_validate(merged)
    return profile


def parse_capabilities(value: str) -> set[Capability]:
    if not value.strip():
        return {Capability.system_messages}
    return {Capability(item.strip()) for item in value.split(",") if item.strip()}


def _deep_merge(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value
