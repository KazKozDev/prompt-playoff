"""The engine model: the LLM this project uses for its own reasoning.

It is deliberately not the model under test. A model that reads your request, or
that proposes a rewrite of its own prompt, is doing the selector's work — folding
that into the model being measured makes the measurement about two things at
once, and lets a model tune a prompt to its own habits while scoring itself on
the result.

Leave the engine unset and every path here falls back to the deterministic
behaviour it replaces, so an engine is an upgrade and never a dependency. When
it is set, the parse is cached on disk: `recommend` and `compile` stay
reproducible for a given description, because the second run reads the same
answer instead of asking again.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from prompt_selector.domain import (
    CompiledProgram,
    CompiledPrompt,
    Constraints,
    Message,
    ModelProfile,
    Priorities,
    TaskProfile,
    TaskShape,
    TaskType,
    TechniqueSpec,
)
from prompt_selector.normalizer import apply_overrides, normalize_description
from prompt_selector.persistence import advisory_lock, atomic_write_json, quarantine_corrupt_file
from prompt_selector.providers import ModelProvider, ProviderError, provider_for
from prompt_selector.templating import placeholders_in

#: Bumped whenever the parse prompt or schema changes, so stale answers in the
#: cache are never replayed against a different question.
PROMPT_VERSION = "4"
AUTHOR_PROMPT_VERSION = "6"

DEFAULT_CACHE_PATH = Path("benchmark-results/engine-cache.json")

#: Above this similarity two paragraphs say the same thing, typos included.
_SAME_PARAGRAPH = 0.9


class EngineTaskParse(BaseModel):
    """What the engine is asked to read out of a free-text description."""

    task_type: TaskType
    domain: str = ""
    complexity: Literal["low", "medium", "high"] = "medium"
    shape: list[TaskShape] = Field(default_factory=list)
    strict_json: bool = False
    tools_allowed: bool = False
    retrieval_required: bool = False
    material_supplied: bool = False
    requires_validation: bool = True
    quality: float = Field(default=0.35, ge=0, le=1)
    reliability: float = Field(default=0.35, ge=0, le=1)
    latency: float = Field(default=0.15, ge=0, le=1)
    token_cost: float = Field(default=0.15, ge=0, le=1)
    reasoning: str = ""

    def priorities(self) -> Priorities | None:
        """None when the engine returned all-zero weights, which Priorities rejects."""
        total = self.quality + self.reliability + self.latency + self.token_cost
        if total <= 0:
            return None
        return Priorities(
            quality=self.quality,
            reliability=self.reliability,
            latency=self.latency,
            token_cost=self.token_cost,
        )


PARSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "task_type": {"type": "string", "enum": [item.value for item in TaskType]},
        "domain": {"type": "string", "description": "Subject area, or empty when general."},
        "complexity": {"type": "string", "enum": ["low", "medium", "high"]},
        "shape": {
            "type": "array",
            "items": {"type": "string", "enum": [item.value for item in TaskShape]},
            "description": "Every trait that is true of this request. One to four.",
        },
        "strict_json": {"type": "boolean"},
        "tools_allowed": {"type": "boolean"},
        "retrieval_required": {"type": "boolean"},
        "material_supplied": {"type": "boolean"},
        "requires_validation": {"type": "boolean"},
        "quality": {"type": "number"},
        "reliability": {"type": "number"},
        "latency": {"type": "number"},
        "token_cost": {"type": "number"},
        "reasoning": {"type": "string", "description": "One sentence, why this task type."},
    },
    "required": [
        "task_type",
        "domain",
        "complexity",
        "shape",
        "strict_json",
        "tools_allowed",
        "retrieval_required",
        "material_supplied",
        "requires_validation",
        "quality",
        "reliability",
        "latency",
        "token_cost",
        "reasoning",
    ],
    "additionalProperties": False,
}

PARSE_SYSTEM = (
    "You classify LLM tasks for a prompt-technique selector. You answer with JSON only, "
    "using the declared fields. You never invent constraints the description does not imply."
)


class PromptAuthoringError(ValueError):
    """The engine did not produce a prompt that preserves the method contract."""


class AuthoredStage(BaseModel):
    stage: str
    system: str = Field(min_length=1)
    user: str = Field(min_length=1)


class AuthoredPrompt(BaseModel):
    stages: list[AuthoredStage] = Field(min_length=1)


AUTHOR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "stages": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "stage": {"type": "string"},
                    "system": {"type": "string"},
                    "user": {"type": "string"},
                },
                "required": ["stage", "system", "user"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["stages"],
    "additionalProperties": False,
}

AUTHOR_SYSTEM = (
    "You are a prompt author. Write the actual prompt that a target model will receive. "
    "Follow the selected technique exactly, but adapt its instructions to the user's real "
    "task. Do not solve the task. The scaffold is a contract, not acceptable prompt text: "
    "rewrite its generic instructions into task-specific instructions. Do not merely paste "
    "the task into a generic INPUT block. "
    "Return JSON only and preserve the declared stage names and runtime placeholders. "
    "The application adds the selected method contract itself, so do not replace the "
    "method with a generic workflow or repeat its recipe as boilerplate."
)

AUTHOR_REPAIR = (
    "\n\nREPAIR REQUIRED\n"
    "Your previous answer was rejected because it copied the deterministic scaffold, changed "
    "the stage contract, or dropped a runtime placeholder. Author a genuinely task-specific "
    "version now. Preserve the exact stage names and placeholders, but express the selected "
    "method as concrete instructions for this user's task. Return the complete JSON object only."
)


def _stage_repair(stages: list[str]) -> str:
    """Name the stages that came back as scaffold boilerplate."""
    named = ", ".join(stages)
    return (
        "\n\nREPAIR REQUIRED\n"
        f"The USER text of these stages repeated the scaffold instead of the task: {named}. "
        "The scaffold text is printed by the application, so repeating it adds nothing. For "
        "each of those stages write only the task-specific part: what this call must produce "
        "for this task, the constraints it must respect, and the exact output format. A later "
        "stage is a prompt in its own right — the model running it sees no earlier message. "
        "Keep the runtime placeholders and stage names exactly. "
        "Return the complete JSON object only."
    )


def _authored_adds_anything(authored: AuthoredPrompt, scaffold: CompiledProgram) -> bool:
    """True when some stage got text the compiled scaffold does not already contain."""
    for written, compiled in zip(authored.stages, scaffold.stages, strict=True):
        for role, text in (("system", written.system), ("user", written.user)):
            compiled_text = next(
                (message.content for message in compiled.messages if message.role == role), ""
            )
            if _squashed(text) not in _squashed(compiled_text):
                return True
    return False


def _copied_stages(authored: AuthoredPrompt, scaffold: CompiledProgram) -> list[str]:
    """Stages whose authored USER text adds nothing to the compiled scaffold."""
    copied: list[str] = []
    for written, compiled in zip(authored.stages, scaffold.stages, strict=True):
        compiled_user = next(
            (message.content for message in compiled.messages if message.role == "user"), ""
        )
        if _squashed(written.user) in _squashed(compiled_user):
            copied.append(written.stage)
    return copied


def _squashed(text: str) -> str:
    return " ".join(text.split())


class TaskNormalization(BaseModel):
    """A task profile plus an honest record of where it came from."""

    profile: TaskProfile
    source: Literal["engine", "engine-cache", "keywords"] = "keywords"
    engine_model_id: str | None = None
    notes: list[str] = Field(default_factory=list)


def engine_profile_from_env() -> ModelProfile | None:
    """`PROMPT_SELECTOR_ENGINE_MODEL` is the one switch that turns the engine on."""
    model_id = os.getenv("PROMPT_SELECTOR_ENGINE_MODEL", "").strip()
    if not model_id:
        return None
    provider = os.getenv("PROMPT_SELECTOR_ENGINE_PROVIDER", "ollama").strip() or "ollama"
    base_url = os.getenv("PROMPT_SELECTOR_ENGINE_BASE_URL", "").strip() or None
    return ModelProfile(
        provider=provider,
        model_id=model_id,
        local=provider == "ollama",
        base_url=base_url,
    )


def resolve_engine_profile(explicit: ModelProfile | None = None) -> ModelProfile | None:
    """An explicit profile always wins; the environment is the fallback, not an override."""
    if explicit is not None and explicit.model_id not in {"", "unknown"}:
        return explicit
    return engine_profile_from_env()


class EngineCache:
    """Disk-backed answers, so a description parsed once parses the same way forever."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _default_cache_path()
        self.lock_path = self.path.with_name(f"{self.path.name}.lock")
        self.corrupt_path: Path | None = None
        self._entries: dict[str, dict[str, Any]] = {}
        self.reload()

    def reload(self) -> None:
        with advisory_lock(self.lock_path):
            self._reload_unlocked()

    def _reload_unlocked(self) -> None:
        if not self.path.exists():
            self._entries = {}
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            try:
                self.corrupt_path = quarantine_corrupt_file(self.path)
            except OSError:
                self.corrupt_path = self.path
            self._entries = {}
            return
        entries = payload.get("entries")
        self._entries = entries if isinstance(entries, dict) else {}

    def get(self, key: str) -> dict[str, Any] | None:
        value = self._entries.get(key)
        return value if isinstance(value, dict) else None

    def put(self, key: str, value: dict[str, Any]) -> None:
        with advisory_lock(self.lock_path):
            self._reload_unlocked()
            self._entries[key] = value
            atomic_write_json(self.path, {"entries": self._entries})

    @property
    def recovery_warning(self) -> str | None:
        if self.corrupt_path is None:
            return None
        return f"Unreadable engine cache was moved to {self.corrupt_path}"


class TaskEngine:
    """Turns a free-text description into a task profile using the engine model.

    Every failure path — no engine configured, provider down, unparseable answer —
    lands on :func:`normalize_description`, the keyword matcher this replaces. The
    caller is told which path ran, because "an LLM read your request" and "six
    substrings matched" are not the same claim.
    """

    def __init__(
        self,
        profile: ModelProfile | None,
        provider: ModelProvider | None = None,
        cache: EngineCache | None = None,
    ) -> None:
        self.profile = profile
        self._provider = provider
        self.cache = cache if cache is not None else EngineCache()

    @property
    def enabled(self) -> bool:
        return self.profile is not None

    def provider(self) -> ModelProvider:
        if self._provider is not None:
            return self._provider
        if self.profile is None:
            raise ProviderError("No engine model configured")
        return provider_for(self.profile)

    async def normalize(
        self,
        description: str,
        model: ModelProfile,
        overrides: dict[str, Any] | None = None,
        timeout_seconds: float = 120,
    ) -> TaskNormalization:
        baseline = normalize_description(description, model, overrides)
        if self.profile is None:
            return TaskNormalization(profile=baseline, source="keywords")

        key = self.cache_key(description)
        cached = self.cache.get(key)
        if cached is not None:
            parsed = _validate(cached)
            if parsed is not None:
                return self._normalization(
                    parsed, baseline, model, overrides, source="engine-cache"
                )

        try:
            payload = await self._ask(description, timeout_seconds)
        except ProviderError as exc:
            return TaskNormalization(
                profile=baseline,
                source="keywords",
                engine_model_id=self.profile.model_id,
                notes=[
                    f"Engine model {self.profile.model_id} was unreachable ({exc}); "
                    "the task profile came from keyword matching instead."
                ],
            )

        parsed = _validate(payload) if payload is not None else None
        if parsed is None:
            return TaskNormalization(
                profile=baseline,
                source="keywords",
                engine_model_id=self.profile.model_id,
                notes=[
                    f"Engine model {self.profile.model_id} returned an answer that does not "
                    "fit the task schema; the task profile came from keyword matching instead."
                ],
            )

        #: The validated form, not the raw answer: nothing unparseable can be replayed.
        self.cache.put(key, parsed.model_dump(mode="json"))
        return self._normalization(parsed, baseline, model, overrides, source="engine")

    async def author(
        self,
        description: str,
        technique: TechniqueSpec,
        scaffold: CompiledProgram,
        reusable: bool = False,
        timeout_seconds: float = 120,
    ) -> CompiledProgram:
        """Ask the engine to author message text; never fall back to the scaffold."""
        if self.profile is None:
            raise PromptAuthoringError(
                "A prompt-writing engine model is required to create a real prompt."
            )
        key = self.author_cache_key(description, technique, scaffold, reusable)
        cached = self.cache.get(key)
        if cached is not None:
            authored = self._validate_authored(
                cached,
                scaffold,
                description=description,
                reusable=reusable,
            )
            if authored is not None:
                return self._merge_authored(
                    description,
                    technique,
                    scaffold,
                    authored,
                    reusable=reusable,
                    cached=True,
                )

        request_text = _author_request(description, technique, scaffold, reusable)
        authored = None
        #: Structurally valid but generic: kept so a failed second attempt is not
        #: worse than no attempt, and used only when the retry cannot beat it.
        generic: AuthoredPrompt | None = None
        copied: list[str] = []
        for attempt in range(2):
            repair = ""
            if attempt:
                repair = AUTHOR_REPAIR if generic is None else _stage_repair(copied)
            prompt = CompiledPrompt(
                technique_id="engine.author",
                stage="author",
                messages=[
                    Message(role="system", content=AUTHOR_SYSTEM),
                    Message(role="user", content=request_text + repair),
                ],
                response_schema=AUTHOR_SCHEMA,
                generation_options={"temperature": 0.0},
            )
            try:
                result = await self.provider().generate(prompt, self.profile, timeout_seconds)
            except ProviderError as exc:
                raise PromptAuthoringError(
                    f"Prompt-writing engine {self.profile.model_id} was unreachable: {exc}"
                ) from exc
            payload = _authored_json(result.content)
            candidate = (
                self._validate_authored(
                    payload,
                    scaffold,
                    description=description,
                    reusable=reusable,
                )
                if payload is not None
                else None
            )
            if candidate is None:
                continue
            # A model that personalises the first stage and pastes the scaffold into
            # the rest passes every structural check, and leaves the later prompts
            # saying nothing about the task. Ask once more, naming the stages.
            copied = _copied_stages(candidate, scaffold)
            if not copied:
                authored = candidate
                break
            generic = candidate
        authored = authored or generic
        if authored is None:
            raise PromptAuthoringError(
                f"Prompt-writing engine {self.profile.model_id} returned an invalid prompt: "
                "neither attempt kept the method's stage names and runtime placeholders, or "
                "neither answered with the requested JSON object. Point "
                "PROMPT_SELECTOR_ENGINE_MODEL at a model that follows a JSON schema — a very "
                "small local model often cannot."
            )
        self.cache.put(key, authored.model_dump(mode="json"))
        return self._merge_authored(
            description,
            technique,
            scaffold,
            authored,
            reusable=reusable,
            cached=False,
        )

    def author_cache_key(
        self,
        description: str,
        technique: TechniqueSpec,
        scaffold: CompiledProgram,
        reusable: bool,
    ) -> str:
        assert self.profile is not None
        payload = {
            "version": AUTHOR_PROMPT_VERSION,
            "provider": self.profile.provider,
            "model": self.profile.model_id,
            "description": description.strip(),
            "reusable": reusable,
            # Python mode, not JSON: it keeps sets as sets, and _canonical can then
            # order them. Dumped straight to JSON a set becomes a list in whatever
            # order this process hashed its members, so the key changed on every
            # restart and the cache never hit.
            "technique": _canonical(technique.model_dump()),
            "scaffold": _canonical(scaffold.model_dump()),
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        return "author:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_authored(
        payload: dict[str, Any],
        scaffold: CompiledProgram,
        *,
        description: str,
        reusable: bool,
    ) -> AuthoredPrompt | None:
        try:
            authored = AuthoredPrompt.model_validate(payload)
        except ValidationError:
            return None
        if [stage.stage for stage in authored.stages] != [stage.stage for stage in scaffold.stages]:
            return None
        declared_anywhere = {
            name for stage in scaffold.stages for name in stage.deferred_placeholders
        }
        aliases = ({stage.stage for stage in scaffold.stages} | {"main"}) - declared_anywhere
        if not reusable:
            aliases.add("input")
        replacement = "{input}" if reusable else description.strip()
        if replacement:
            authored = authored.model_copy(
                update={
                    "stages": [
                        stage.model_copy(
                            update={
                                "system": _replace_input_aliases(
                                    stage.system, aliases, replacement
                                ),
                                "user": _replace_input_aliases(stage.user, aliases, replacement),
                            }
                        )
                        for stage in authored.stages
                    ]
                }
            )
        has_reusable_input = False
        for written, compiled in zip(authored.stages, scaffold.stages, strict=True):
            combined = f"{written.system}\n{written.user}"
            declared = set(compiled.deferred_placeholders)
            allowed = declared | ({"input"} if reusable else set())
            present = placeholders_in(combined)
            if not declared.issubset(present):
                return None
            # The author model may only preserve runtime slots declared by the
            # compiler. Invented tokens such as {main} make an otherwise ready
            # prompt unusable and must fail closed.
            if present - allowed:
                return None
            has_reusable_input = has_reusable_input or "input" in present
        if reusable and not has_reusable_input:
            return None
        # An answer that repeats the scaffold is a poor answer, not an unusable
        # one: the stages, the placeholders and the method survive it. That case
        # is caught by _copied_stages, which asks again and then says so in the
        # notes. Failing here instead left the caller with nothing at all.
        return authored

    def _merge_authored(
        self,
        description: str,
        technique: TechniqueSpec,
        scaffold: CompiledProgram,
        authored: AuthoredPrompt,
        reusable: bool,
        cached: bool,
    ) -> CompiledProgram:
        assert self.profile is not None
        stages = []
        source_stage = 0
        if not reusable and scaffold.source_input.strip():
            source_stage = next(
                (
                    index
                    for index, stage in enumerate(scaffold.stages)
                    if any(
                        message.role == "user" and scaffold.source_input.strip() in message.content
                        for message in stage.messages
                    )
                ),
                0,
            )
        for stage_index, (compiled, written) in enumerate(
            zip(scaffold.stages, authored.stages, strict=True)
        ):
            method_contract = _method_contract(technique, compiled.stage, scaffold.strategy)
            authored_system = written.system.strip()
            system = (
                method_contract
                if authored_system == technique.recipe.system.strip()
                else f"{authored_system}\n\n{method_contract}".strip()
            )
            # The registry technique, not the author model, owns the executable
            # prompt structure. Keep its selected blocks and stage-specific
            # placeholders verbatim; the model may only add task-aware guidance.
            compiled_user = next(
                (message.content for message in compiled.messages if message.role == "user"), ""
            ).strip()
            authored_user = written.user.strip()
            user = compiled_user
            if authored_user and authored_user not in compiled_user:
                user = _merge_user_text(compiled_user, authored_user, technique)
                if not set(compiled.deferred_placeholders) <= placeholders_in(user):
                    user = f"{compiled_user}\n\nTASK-SPECIFIC GUIDANCE\n{authored_user}".strip()
            source_input = description.strip()
            if (
                not reusable
                and stage_index == source_stage
                and source_input
                and source_input not in user
            ):
                user = f"{user}\n\nORIGINAL USER TASK\n{source_input}"
            stages.append(
                compiled.model_copy(
                    update={
                        "messages": [
                            Message(role="system", content=system),
                            Message(role="user", content=user),
                        ]
                    }
                )
            )
        # Whether the engine actually contributed is decided by the text it wrote,
        # not by the fact that a model was called: a model that echoed the scaffold
        # must not leave an artifact claiming an author. Comparing the merged
        # messages would not do — the method contract makes every system differ.
        wrote_something = _authored_adds_anything(authored, scaffold)
        cached_label = " (cached)" if cached else ""
        note = (
            f"Prompt text authored by engine model {self.profile.model_id}{cached_label}; "
            "execution, validators, and fallback remain those of the selected technique."
            if wrote_something
            else (
                f"Engine model {self.profile.model_id}{cached_label} answered with the method's "
                "own wording and added nothing about this task, so this is the compiled "
                "technique with your task in it. A larger engine model usually adds the "
                "task-specific detail."
            )
        )
        return scaffold.model_copy(
            update={
                "stages": stages,
                "notes": [note, *scaffold.notes],
                "artifact_source": "engine" if wrote_something else "deterministic_compiler",
                "authored_by_model": self.profile.model_id if wrote_something else None,
                "authored_by_provider": self.profile.provider if wrote_something else None,
            }
        )

    def cache_key(self, description: str) -> str:
        assert self.profile is not None
        raw = "|".join(
            [PROMPT_VERSION, self.profile.provider, self.profile.model_id, description.strip()]
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    async def _ask(self, description: str, timeout_seconds: float) -> dict[str, Any] | None:
        assert self.profile is not None
        prompt = CompiledPrompt(
            technique_id="engine.parse",
            stage="parse",
            messages=[
                Message(role="system", content=PARSE_SYSTEM),
                Message(role="user", content=_parse_request(description)),
            ],
            response_schema=PARSE_SCHEMA,
            # The parse must be repeatable before the cache exists to make it so.
            generation_options={"temperature": 0.0},
        )
        result = await self.provider().generate(prompt, self.profile, timeout_seconds)
        #: A model that answers with prose is a bad answer, not a broken provider —
        #: the two get different notes, so the fix is obvious from the message.
        return _json_object(result.content)

    def _normalization(
        self,
        parsed: EngineTaskParse,
        baseline: TaskProfile,
        model: ModelProfile,
        overrides: dict[str, Any] | None,
        source: Literal["engine", "engine-cache"],
    ) -> TaskNormalization:
        assert self.profile is not None
        profile = _profile_from_parse(parsed, baseline, model)
        if overrides:
            profile = apply_overrides(profile, overrides)
        reason = (parsed.reasoning.strip() or parsed.task_type.value).rstrip(".")
        notes = [
            f"Task profile read by engine model {self.profile.model_id}"
            f"{' (cached)' if source == 'engine-cache' else ''}: {reason}."
        ]
        if parsed.task_type != baseline.task_type:
            notes.append(
                f"Keyword matching would have chosen {baseline.task_type.value}; "
                f"the engine chose {parsed.task_type.value}."
            )
        return TaskNormalization(
            profile=profile,
            source=source,
            engine_model_id=self.profile.model_id,
            notes=notes,
        )


def _parse_request(description: str) -> str:
    return (
        "Read the task description and fill every field.\n\n"
        "task_type — pick exactly one: " + ", ".join(item.value for item in TaskType) + ".\n"
        "shape — every trait below that is true of THIS request, one to four of them. This is "
        "what decides the method, so read the description for it rather than guessing from the "
        "task type:\n"
        "  multi_step — the work splits into steps that depend on each other.\n"
        "  verifiable — there is a right answer that can be checked once it exists.\n"
        "  underspecified — the request leaves material questions open.\n"
        "  long_input — the material to work through is long.\n"
        "  exact_format — the output has to match a fixed shape (schema, table, template).\n"
        "  has_examples — the description supplies demonstrations of what is wanted.\n"
        "  open_ended — many answers are valid and quality is a judgement.\n"
        "  high_stakes — a wrong answer is expensive.\n"
        "  computational — getting there needs arithmetic or an algorithm.\n"
        "strict_json — true only when the output must be machine-parseable JSON.\n"
        "tools_allowed — true only when the task needs external tools, search or a browser.\n"
        "retrieval_required — true when the description asks for material that is not in the "
        "description itself and has to be found (the web, a corpus, a database). False when the "
        "text to work on is pasted in or supplied at runtime.\n"
        "material_supplied — true when the description itself carries the text or data to work "
        "on: a pasted document, a list, code, a transcript. False when it only names a topic or "
        "states what to do. A request can be long and still supply nothing.\n"
        "requires_validation — true when a wrong answer must be caught before it is used.\n"
        "quality, reliability, latency, token_cost — weights in 0..1 summing to about 1. "
        "Read them off the task, not off the words: work whose errors are expensive weighs "
        "reliability, throwaway or interactive work weighs latency, bulk work over long "
        "material weighs token_cost. Use 0.35 / 0.35 / 0.15 / 0.15 only when the description "
        "really gives you nothing to go on.\n"
        "reasoning — one sentence naming the words that decided the task type.\n\n"
        f"TASK DESCRIPTION\n{description.strip()}"
    )


def _author_request(
    description: str,
    technique: TechniqueSpec,
    scaffold: CompiledProgram,
    reusable: bool,
) -> str:
    required = {
        stage.stage: [f"{{{name}}}" for name in stage.deferred_placeholders]
        for stage in scaffold.stages
    }
    recipe = technique.model_dump(mode="json")
    scaffold_messages = [
        {
            "stage": stage.stage,
            "system": next(
                (message.content for message in stage.messages if message.role == "system"), ""
            ),
            "user": next(
                (message.content for message in stage.messages if message.role == "user"), ""
            ),
        }
        for stage in scaffold.stages
    ]
    mode = (
        "REUSABLE: keep {input} as runtime content and never replace it with the description. "
        "The final prompt must contain {input}."
        if reusable
        else "DIRECT: write a prompt specifically for this task; the user will paste it as-is. "
        "Do not introduce any runtime placeholder."
    )
    return (
        f"MODE\n{mode}\n\n"
        "AUTHORING RULES\n"
        "- Write concrete, task-aware SYSTEM and USER instructions for every stage.\n"
        "- Every stage is a separate call and the model running it sees no earlier message. "
        "Later stages must name the deliverable, the constraints and the output format in the "
        "task's own terms, not just refer to the previous step.\n"
        "- The application prints the scaffold's own USER blocks and merges your USER text "
        "into them, so a stage whose USER text repeats the scaffold contributes nothing and is "
        "rejected. Write only what the scaffold does not already say about this task.\n"
        "- Add task-specific acceptance criteria and implementation details "
        "inferred from the task.\n"
        "- Encode the deliverable, constraints, process, and output format from the task.\n"
        "- Use the recipe's instructions, blocks, stage conditions, validators, and fallback.\n"
        "- Make the authored text task-specific. Do not turn every method into the same "
        "generic role / objective / constraints template.\n"
        "- Do not copy the recipe's method rules as boilerplate; the application appends a "
        "canonical selected-method contract after your task-specific SYSTEM text.\n"
        "- Keep every stage name exactly and in order.\n"
        "- Keep every required runtime placeholder verbatim.\n"
        "- Never invent placeholders. In particular, stage names such as {main} are not "
        "runtime inputs. Use only placeholders listed under REQUIRED RUNTIME PLACEHOLDERS, "
        "plus {input} in REUSABLE mode.\n"
        "- Do not mention this authoring request or explain your choices.\n\n"
        f"USER TASK\n{description.strip()}\n\n"
        f"REQUIRED RUNTIME PLACEHOLDERS\n{json.dumps(required, ensure_ascii=False)}\n\n"
        "FULL TECHNIQUE RECIPE\n"
        f"{json.dumps(recipe, ensure_ascii=False, sort_keys=True)}\n\n"
        "DETERMINISTIC EXECUTION SCAFFOLD\n"
        f"{json.dumps(scaffold_messages, ensure_ascii=False)}"
    )


def _merge_user_text(compiled_user: str, authored_user: str, technique: TechniqueSpec) -> str:
    """Fold task-specific text into the scaffold's own sections instead of beside them.

    Author models tend to answer with the scaffold's headings and task-specific
    bodies under them. Appending that wholesale printed every heading twice and
    the user's task twice — once in the technique's input block, once in the
    copy. Matching headings replace the generic body; blocks that carry a
    placeholder stay exactly as compiled, because they hold the runtime slots.
    """
    titles = [block.title for block in technique.recipe.blocks if block.title]
    locked = {
        block.title.strip().casefold()
        for block in technique.recipe.blocks
        if block.title and placeholders_in(block.body)
    }
    authored_sections = _split_titled(authored_user, titles)
    if not any(title for title, _ in authored_sections):
        guidance = _without_slots(
            _unsaid(authored_user, compiled_user), placeholders_in(compiled_user)
        )
        if not guidance:
            return compiled_user
        return f"{compiled_user}\n\nTASK-SPECIFIC GUIDANCE\n{guidance}".strip()

    extra: list[str] = []
    by_title: dict[str, str] = {}
    for title, body in authored_sections:
        if title is None or title.strip().casefold() in locked:
            # The scaffold owns blocks that carry a runtime slot, but anything the
            # author added around one is still task-specific: keep it as guidance.
            extra.append(body)
        elif body and title not in by_title:
            by_title[title] = body

    used: set[str] = set()
    parts: list[str] = []
    for title, body in _split_titled(compiled_user, titles):
        if title is not None and title in by_title:
            body = by_title[title]
            used.add(title)
        parts.append(f"{title}\n{body}" if title else body)

    text = "\n\n".join(section for section in parts if section.strip()).strip()
    leftover = [
        f"{title}\n{body}" for title, body in by_title.items() if title not in used and body
    ]
    # Whatever the scaffold already says needs no second voice, and a runtime slot
    # it already holds must not appear twice: {previous} pasted in two places would
    # be filled in two places.
    guidance = "\n\n".join(
        kept for section in [*extra, *leftover] if (kept := _unsaid(section, text))
    ).strip()
    guidance = _without_slots(guidance, placeholders_in(text))
    if guidance:
        text = f"{text}\n\nTASK-SPECIFIC GUIDANCE\n{guidance}"
    return text


def _canonical(value: Any) -> Any:
    """Order the unordered so a cache key is the same in every process."""
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, set | frozenset):
        return sorted(str(item) for item in value)
    if isinstance(value, list | tuple):
        return [_canonical(item) for item in value]
    return value


#: What a runtime slot is called in prose, for guidance text that refers to a slot
#: the prompt already carries. Deleting the token outright left dangling sentences
#: like "based on the subproblems in .".
_SLOT_PROSE = {
    "previous": "the previous step's output",
    "partials": "the partial results above",
    "input": "the input above",
}


def _without_slots(text: str, slots: set[str]) -> str:
    """Name, rather than repeat, placeholders the prompt fills elsewhere."""
    for name in slots:
        text = text.replace(f"{{{name}}}", _SLOT_PROSE.get(name, f"the {name} above"))
    text = re.sub(r"[ \t]{2,}", " ", text)
    lines = [line.rstrip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _unsaid(text: str, existing: str) -> str:
    """Drop the paragraphs of `text` the prompt already contains.

    Near-matches count: author models retype the task rather than copy it, and a
    restatement with a typo in it is still the same paragraph twice.
    """
    known = _squashed(existing)
    already = [_squashed(part) for part in re.split(r"\n\s*\n", existing) if part.strip()]
    kept: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text):
        squashed = _squashed(paragraph)
        if not squashed or squashed in known:
            continue
        if any(
            SequenceMatcher(None, squashed, other).ratio() >= _SAME_PARAGRAPH for other in already
        ):
            continue
        kept.append(paragraph)
    return "\n\n".join(kept).strip()


def _split_titled(text: str, titles: list[str]) -> list[tuple[str | None, str]]:
    """Split rendered prompt text on the technique's own block titles."""
    known = {title.strip().casefold(): title for title in titles if title.strip()}
    sections: list[tuple[str | None, list[str]]] = []
    title: str | None = None
    lines: list[str] = []
    for line in text.splitlines():
        heading = known.get(line.strip().casefold())
        if heading is None:
            lines.append(line)
            continue
        if title is not None or any(item.strip() for item in lines):
            sections.append((title, lines))
        title, lines = heading, []
    if title is not None or any(item.strip() for item in lines):
        sections.append((title, lines))
    return [(name, "\n".join(body).strip()) for name, body in sections]


def _method_contract(
    technique: TechniqueSpec,
    stage: str,
    strategy: str,
) -> str:
    """Keep the selected technique visible even when an author model paraphrases it.

    Prompt authors are useful for task-specific detail, but they are not trusted to
    preserve the method: a plausible generic rewrite can otherwise satisfy the JSON
    and placeholder checks.  These lines come from the registry, not from the model.
    """
    rules = "\n".join(f"- {instruction.strip()}" for instruction in technique.recipe.instructions)
    parts = [
        f"SELECTED METHOD: {technique.title} ({technique.id})",
        f"EXECUTION: {strategy}; stage: {stage}",
        technique.recipe.system.strip(),
    ]
    if rules:
        parts.extend(["METHOD RULES", rules])
    return "\n".join(part for part in parts if part)


def _profile_from_parse(
    parsed: EngineTaskParse,
    baseline: TaskProfile,
    model: ModelProfile,
) -> TaskProfile:
    priorities = parsed.priorities() or baseline.priorities
    #: An engine that names no trait tells the selector nothing; the keyword reading
    #: is coarse but real, so it stands in rather than leaving the request shapeless.
    shape = set(parsed.shape) or baseline.shape
    if parsed.strict_json:
        shape = shape | {TaskShape.exact_format}
    return TaskProfile(
        task_type=parsed.task_type,
        domain=parsed.domain.strip() or None,
        complexity=parsed.complexity,
        shape=shape,
        output_contract="json_schema" if parsed.strict_json else "free_text",
        priorities=priorities,
        constraints=Constraints(
            local_only=baseline.constraints.local_only or model.local,
            max_calls=baseline.constraints.max_calls,
            tools_allowed=parsed.tools_allowed or parsed.retrieval_required,
            retrieval_required=parsed.retrieval_required,
            supplied_material=parsed.material_supplied,
            strict_json=parsed.strict_json,
            requires_validation=parsed.requires_validation or parsed.strict_json,
        ),
        model=model,
    )


def _validate(payload: dict[str, Any]) -> EngineTaskParse | None:
    try:
        return EngineTaskParse.model_validate(payload)
    except ValidationError:
        return None


def _json_fragments(content: str) -> list[Any]:
    """Every JSON object or array in the answer, whatever surrounds them.

    Models put the JSON behind a sentence, inside a fence, or after a block of
    reasoning, and a greedy "first brace to last brace" match reads all of that
    as one broken document — or, for a top-level array, returns the first stage
    object and drops the rest. Scanning for balanced fragments costs nothing and
    is the difference between an answer that works and a hard failure.
    """
    text = content or ""
    fragments: list[Any] = []
    index = 0
    while index < len(text):
        if text[index] not in "{[":
            index += 1
            continue
        end = _balanced_end(text, index)
        if end is None:
            index += 1
            continue
        try:
            fragments.append(json.loads(text[index : end + 1]))
        except json.JSONDecodeError:
            index += 1
            continue
        index = end + 1
    return fragments


def _balanced_end(text: str, start: int) -> int | None:
    """Index of the bracket closing the one at `start`, ignoring brackets in strings."""
    closing = {"{": "}", "[": "]"}
    expected = [closing[text[start]]]
    in_string = False
    escaped = False
    for index in range(start + 1, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in closing:
            expected.append(closing[char])
        elif char in "}]":
            if not expected or char != expected.pop():
                return None
            if not expected:
                return index
    return None


def _json_object(content: str) -> dict[str, Any] | None:
    return next((value for value in _json_fragments(content) if isinstance(value, dict)), None)


def _authored_json(content: str) -> dict[str, Any] | None:
    """The stages, however the model chose to shape them.

    The schema asks for `{"stages": [{stage, system, user}]}`. Models answer with
    a bare array, or key the object by stage name, or emit the stage objects one
    after another. All three say exactly the same thing, and rejecting them cost
    the caller a prompt over punctuation.
    """
    fragments = _json_fragments(content)
    for value in fragments:
        stages = _as_stages(value)
        if stages:
            return {"stages": stages}
    loose = [
        value
        for value in fragments
        if isinstance(value, dict) and {"stage", "system", "user"} <= value.keys()
    ]
    return {"stages": loose} if loose else None


def _as_stages(value: Any) -> list[Any] | None:
    if isinstance(value, list):
        return value or None
    if not isinstance(value, dict):
        return None
    inner = value.get("stages", value)
    if isinstance(inner, list):
        return inner or None
    #: `{"draft": {...}, "answer": {...}}` — the stage names used as keys.
    if (
        isinstance(inner, dict)
        and inner
        and all(
            isinstance(item, dict) and {"system", "user"} <= item.keys() for item in inner.values()
        )
    ):
        return [{"stage": name, **item} for name, item in inner.items()]
    return None


def _replace_input_aliases(text: str, aliases: set[str], replacement: str) -> str:
    """Repair common author-model aliases without accepting arbitrary placeholders."""
    for alias in aliases:
        text = text.replace(f"{{{alias}}}", replacement)
    return text


def _default_cache_path() -> Path:
    custom = os.getenv("PROMPT_SELECTOR_ENGINE_CACHE")
    if custom:
        return Path(custom).expanduser()
    return DEFAULT_CACHE_PATH
