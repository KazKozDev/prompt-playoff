from __future__ import annotations

from typing import Any

from prompt_playoff.domain import (
    Capability,
    Constraints,
    ModelProfile,
    Priorities,
    TaskProfile,
    TaskShape,
    TaskType,
)

TASK_KEYWORDS: list[tuple[TaskType, tuple[str, ...]]] = [
    (TaskType.structured_extraction, ("extract", "извлеч", "json", "schema", "entity", "сущност")),
    (TaskType.translation, ("translate", "translation", "перевод", "перевед")),
    (
        TaskType.coding,
        (
            "code",
            "coding",
            "program",
            "debug",
            "function",
            "refactor",
            "script",
            "bug",
            "python",
            "код",
            "программ",
            "пайтон",
            "на питон",
            "в питон",
            "функци",
            "рефактор",
            "скрипт",
            "баг",
            "спроектируй сервис",
            "спроектируй систему",
        ),
    ),
    (TaskType.research, ("research", "sources", "citation", "исслед", "источник")),
    (TaskType.classification, ("classify", "classification", "label", "классиф")),
    (TaskType.agents, ("agent", "tool calling", "react", "агент", "инструмент")),
    (TaskType.summarization, ("summar", "резюм", "сводк")),
    (TaskType.creative_writing, ("creative", "story", "novel", "write a book", "рассказ", "роман")),
]

#: Words that say the material has to be fetched, not that it is attached.
RETRIEVAL_KEYWORDS: tuple[str, ...] = (
    "интернет",
    "в сети",
    "онлайн",
    "собери",
    "собрать",
    "найди",
    "найти",
    "поищ",
    "загугл",
    "web search",
    "search the web",
    "on the web",
    "online",
    "internet",
    "browse",
    "google",
    "look up",
    "crawl",
    "scrape",
)


#: Substrings that give a request trait away without an engine model. Coarse on
#: purpose: this path exists so a selection without an LLM is still about the
#: request rather than about its task type alone.
SHAPE_KEYWORDS: list[tuple[TaskShape, tuple[str, ...]]] = [
    (
        TaskShape.multi_step,
        (
            "step by step",
            "step-by-step",
            "then ",
            "after that",
            "pipeline",
            "workflow",
            "по шагам",
            "пошагов",
            "сначала",
            "затем",
            "потом",
            "план",
        ),
    ),
    (
        TaskShape.verifiable,
        (
            "correct",
            "test",
            "verify",
            "check",
            "правильн",
            "провер",
            "тест",
            "без ошибок",
        ),
    ),
    (
        TaskShape.long_input,
        (
            "long document",
            "whole file",
            "transcript",
            "attached",
            "below",
            "документ",
            "стенограмм",
            "длинн",
            "ниже текст",
            "текст ниже",
        ),
    ),
    (
        TaskShape.exact_format,
        (
            "json",
            "schema",
            "csv",
            "table",
            "markdown",
            "template",
            "format",
            "columns",
            "таблиц",
            "формат",
            "колонк",
            "шаблон",
        ),
    ),
    (
        TaskShape.has_examples,
        ("for example", "example:", "examples:", "few-shot", "пример:", "примеры:", "например:"),
    ),
    (
        TaskShape.open_ended,
        (
            "creative",
            "brainstorm",
            "ideas",
            "story",
            "рассказ",
            "идеи",
            "придумай",
            "варианты",
        ),
    ),
    (
        TaskShape.high_stakes,
        (
            "critical",
            "production",
            "legal",
            "medical",
            "compliance",
            "must not",
            "критич",
            "юридич",
            "медицин",
            "нельзя ошиб",
            "важно",
        ),
    ),
    (
        TaskShape.computational,
        (
            "calculate",
            "compute",
            "how many",
            "percent",
            "посчита",
            "вычисл",
            "сколько будет",
            "процент",
        ),
    ),
]

#: Task types whose requests are checkable by their nature, whatever the wording.
VERIFIABLE_TASKS = {TaskType.coding, TaskType.structured_extraction, TaskType.classification}

#: Below this a request cannot be carrying the document it talks about. Above it,
#: the words may be the material, and nothing here can tell — so the benefit of the
#: doubt goes to the recipes that read an input, which is what a long request wants.
MATERIAL_WORDS = 40


def has_material(description: str) -> bool:
    """Whether the request looks like it carries the text or data to work on."""
    return len(description.split()) >= MATERIAL_WORDS


def read_shape(description: str, task_type: TaskType, strict_json: bool) -> set[TaskShape]:
    """The traits of this request, as far as substrings can tell."""
    text = description.lower()
    shape = {trait for trait, keywords in SHAPE_KEYWORDS if any(word in text for word in keywords)}
    #: Only a request that is both very short and gave up no other trait counts as
    #: underspecified. Length alone is a bad judge — "classify these tickets by
    #: category" is short and perfectly clear — and reading intent out of prose is
    #: the engine model's job, not this fallback's.
    if len(description.split()) <= 4 and not shape:
        shape.add(TaskShape.underspecified)
    if strict_json:
        shape.add(TaskShape.exact_format)
    if task_type in VERIFIABLE_TASKS:
        shape.add(TaskShape.verifiable)
    if task_type is TaskType.creative_writing:
        shape.add(TaskShape.open_ended)
    return shape


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
    #: Acquisition verbs and places, not the word "source": "answer from these sources"
    #: supplies the evidence, "collect from the internet" says nobody has yet.
    retrieval_required = any(token in text for token in RETRIEVAL_KEYWORDS)
    tools_allowed = (
        any(token in text for token in ("tool", "browser", "search", "инструмент", "браузер"))
        or retrieval_required
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
        shape=read_shape(description, task_type, strict_json),
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
            retrieval_required=retrieval_required,
            supplied_material=has_material(description),
            strict_json=strict_json,
            requires_validation=strict_json
            or task_type in {TaskType.coding, TaskType.structured_extraction},
        ),
        model=model,
    )
    return apply_overrides(profile, overrides) if overrides else profile


def apply_overrides(profile: TaskProfile, overrides: dict[str, Any] | None) -> TaskProfile:
    """Caller-supplied fields win over anything inferred, whatever inferred it."""
    if not overrides:
        return profile
    merged = profile.model_dump(mode="json")
    _deep_merge(merged, overrides)
    return TaskProfile.model_validate(merged)


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
