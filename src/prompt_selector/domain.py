from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TaskType(StrEnum):
    structured_extraction = "structured_extraction"
    classification = "classification"
    translation = "translation"
    coding = "coding"
    research = "research"
    agents = "agents"
    summarization = "summarization"
    creative_writing = "creative_writing"


class ModelClass(StrEnum):
    small = "small"
    medium = "medium"
    large = "large"
    reasoning = "reasoning"


class Capability(StrEnum):
    structured_output = "structured_output"
    tool_calling = "tool_calling"
    vision = "vision"
    reasoning_control = "reasoning_control"
    system_messages = "system_messages"


class EvidenceLevel(StrEnum):
    heuristic = "heuristic"
    documented = "documented"
    benchmarked = "benchmarked"
    replicated = "replicated"


class Priorities(BaseModel):
    quality: float = Field(default=0.35, ge=0)
    reliability: float = Field(default=0.35, ge=0)
    latency: float = Field(default=0.15, ge=0)
    token_cost: float = Field(default=0.15, ge=0)

    @model_validator(mode="after")
    def require_nonzero_total(self) -> Priorities:
        if self.total <= 0:
            raise ValueError("At least one priority weight must be greater than zero")
        return self

    @property
    def total(self) -> float:
        return self.quality + self.reliability + self.latency + self.token_cost

    def normalized(self) -> Priorities:
        total = self.total
        return Priorities(
            quality=self.quality / total,
            reliability=self.reliability / total,
            latency=self.latency / total,
            token_cost=self.token_cost / total,
        )


class Constraints(BaseModel):
    local_only: bool = False
    max_calls: int = Field(default=3, ge=1, le=20)
    tools_allowed: bool = False
    strict_json: bool = False
    requires_validation: bool = True
    max_latency_seconds: float | None = Field(default=None, gt=0)
    max_output_tokens: int | None = Field(default=None, ge=1)


class ModelProfile(BaseModel):
    provider: str = "ollama"
    model_id: str = "unknown"
    model_class: ModelClass = ModelClass.medium
    local: bool = True
    context_window: int = Field(default=8192, ge=512)
    capabilities: set[Capability] = Field(default_factory=lambda: {Capability.system_messages})
    base_url: str | None = None
    notes: list[str] = Field(default_factory=list)


class TaskProfile(BaseModel):
    task_type: TaskType
    domain: str | None = None
    input_modality: str = "text"
    output_contract: str = "free_text"
    complexity: str = "medium"
    priorities: Priorities = Field(default_factory=Priorities)
    constraints: Constraints = Field(default_factory=Constraints)
    model: ModelProfile = Field(default_factory=ModelProfile)


class TechniqueCharacteristics(BaseModel):
    quality: float = Field(ge=0, le=1)
    reliability: float = Field(ge=0, le=1)
    latency_efficiency: float = Field(ge=0, le=1)
    token_efficiency: float = Field(ge=0, le=1)
    simplicity: float = Field(ge=0, le=1)


class BlockCondition(StrEnum):
    """Closed vocabulary of render conditions, so recipes never execute code."""

    always = "always"
    has_schema = "has_schema"
    native_schema = "native_schema"
    embedded_schema = "embedded_schema"
    strict_json = "strict_json"
    free_text = "free_text"
    has_exemplars = "has_exemplars"
    tools_allowed = "tools_allowed"
    requires_validation = "requires_validation"
    has_domain = "has_domain"
    reasoning_control = "reasoning_control"


class PromptBlock(BaseModel):
    """One addressable section of the user message."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    title: str | None = None
    body: str
    when: BlockCondition = BlockCondition.always


class Exemplar(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input: str
    output: str
    note: str | None = None


class StageSpec(BaseModel):
    """One model call inside a multi-call technique."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    blocks: list[str] = Field(default_factory=list)
    system: str | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    carries_schema: bool = True
    description: str | None = None


class ExecutionSpec(BaseModel):
    """How the compiled stages are actually executed against a provider."""

    model_config = ConfigDict(extra="forbid")

    strategy: str = "single"
    params: dict[str, Any] = Field(default_factory=dict)
    stages: list[StageSpec] = Field(default_factory=list)


class PromptRecipe(BaseModel):
    model_config = ConfigDict(extra="forbid")

    system: str
    instructions: list[str] = Field(default_factory=list)
    blocks: list[PromptBlock] = Field(default_factory=list)
    exemplars: list[Exemplar] = Field(default_factory=list)
    variables: dict[str, str] = Field(default_factory=dict)
    validators: list[str] = Field(default_factory=list)
    fallback: str | None = None

    @field_validator("blocks")
    @classmethod
    def unique_block_names(cls, value: list[PromptBlock]) -> list[PromptBlock]:
        names = [block.name for block in value]
        duplicates = {name for name in names if names.count(name) > 1}
        if duplicates:
            raise ValueError(f"Duplicate block names: {', '.join(sorted(duplicates))}")
        return value


class TechniqueSource(BaseModel):
    """Where a technique comes from.

    Without this, `evidence_level: documented` is a claim nobody can check. The
    lint rule ties the two together: claim published evidence, name the paper.
    """

    model_config = ConfigDict(extra="forbid")

    paper: str
    authors: str | None = None
    url: str | None = None
    year: int | None = Field(default=None, ge=1990, le=2100)
    note: str | None = None


class TechniqueSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    version: str
    title: str
    family: str
    description: str
    strong_tasks: set[TaskType] = Field(default_factory=set)
    acceptable_tasks: set[TaskType] = Field(default_factory=set)
    avoid_tasks: set[TaskType] = Field(default_factory=set)
    required_capabilities: set[Capability] = Field(default_factory=set)
    model_classes: set[ModelClass] = Field(default_factory=set)
    min_calls: int = Field(default=1, ge=1)
    tools_required: bool = False
    strict_json_fit: bool = False
    validation_fit: bool = False
    characteristics: TechniqueCharacteristics
    recipe: PromptRecipe
    execution: ExecutionSpec = Field(default_factory=ExecutionSpec)
    #: The publication this technique comes from, if any. Required by lint once
    #: evidence_level claims more than a heuristic.
    source: TechniqueSource | None = None
    benchmark_priors: dict[str, float] = Field(default_factory=dict)
    evidence_level: EvidenceLevel = EvidenceLevel.heuristic
    tags: set[str] = Field(default_factory=set)

    @field_validator("benchmark_priors")
    @classmethod
    def validate_priors(cls, value: dict[str, float]) -> dict[str, float]:
        for key, score in value.items():
            if not 0 <= score <= 1:
                raise ValueError(f"Benchmark prior {key!r} must be between 0 and 1")
        return value

    @model_validator(mode="after")
    def validate_stage_blocks(self) -> TechniqueSpec:
        known = {block.name for block in self.recipe.blocks}
        for stage in self.execution.stages:
            unknown = [name for name in stage.blocks if name not in known]
            if unknown:
                raise ValueError(
                    f"Stage {stage.name!r} references unknown blocks: {', '.join(unknown)}"
                )
        return self


class MeasuredEvidence(BaseModel):
    """A real benchmark result recorded for a (technique, task, model) triple."""

    technique_id: str
    task_type: TaskType
    provider: str
    model_id: str
    quality: float = Field(ge=0, le=1)
    reliability: float = Field(ge=0, le=1)
    mean_latency_seconds: float = Field(ge=0)
    mean_total_tokens: float = Field(ge=0)
    examples: int = Field(ge=1)
    repeats: int = Field(ge=1)
    dataset: str
    recorded_at: str


class ScoreBreakdown(BaseModel):
    task_fit: float
    model_fit: float
    priority_fit: float
    benchmark_prior: float
    evidence_quality: float
    penalties: float


class Recommendation(BaseModel):
    technique_id: str
    title: str
    family: str
    score: float
    confidence: float
    reasons: list[str]
    breakdown: ScoreBreakdown
    evidence_source: str = "prior"
    measured: MeasuredEvidence | None = None


class Rejection(BaseModel):
    technique_id: str
    title: str
    reasons: list[str]


class SelectionResult(BaseModel):
    recommendations: list[Recommendation]
    rejected: list[Rejection]
    warnings: list[str] = Field(default_factory=list)
    #: The profile the ranking was computed against. Returned so a client can
    #: reuse the exact same task for compile, benchmark and optimize.
    task: TaskProfile | None = None


class Message(BaseModel):
    role: str
    content: str


class CompiledPrompt(BaseModel):
    """A single ready-to-send model call."""

    technique_id: str
    stage: str = "main"
    messages: list[Message]
    response_schema: dict[str, Any] | None = None
    tools: list[dict[str, Any]] = Field(default_factory=list)
    generation_options: dict[str, Any] = Field(default_factory=dict)
    validators: list[str] = Field(default_factory=list)
    fallback: str | None = None
    think: bool | str | None = None
    deferred_placeholders: list[str] = Field(default_factory=list)


class CompiledProgram(BaseModel):
    """Everything needed to execute one technique end to end."""

    technique_id: str
    technique_title: str
    technique_version: str
    strategy: str
    strategy_params: dict[str, Any] = Field(default_factory=dict)
    stages: list[CompiledPrompt]
    response_schema: dict[str, Any] | None = None
    validators: list[str] = Field(default_factory=list)
    fallback: str | None = None
    expected_calls: int = 1
    notes: list[str] = Field(default_factory=list)
    #: Raw task input, kept so chunking strategies operate on the source rather
    #: than on rendered prompt text.
    source_input: str = ""

    @property
    def main(self) -> CompiledPrompt:
        return self.stages[0]


class ModelResult(BaseModel):
    content: str
    thinking: str | None = None
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    usage: dict[str, Any] = Field(default_factory=dict)
    raw: dict[str, Any] = Field(default_factory=dict)


class CallRecord(BaseModel):
    """One real provider call, with measured cost."""

    stage: str
    index: int
    content: str
    latency_seconds: float
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class ExecutionTrace(BaseModel):
    technique_id: str
    strategy: str
    output: str
    calls: list[CallRecord] = Field(default_factory=list)
    aggregation: dict[str, Any] = Field(default_factory=dict)

    @property
    def latency_seconds(self) -> float:
        return round(sum(call.latency_seconds for call in self.calls), 4)

    @property
    def prompt_tokens(self) -> int:
        return sum(call.prompt_tokens for call in self.calls)

    @property
    def completion_tokens(self) -> int:
        return sum(call.completion_tokens for call in self.calls)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class CompileRequest(BaseModel):
    task: TaskProfile
    user_input: str
    response_schema: dict[str, Any] | None = None
    technique_id: str | None = None
    variables: dict[str, str] = Field(default_factory=dict)
    #: Few-shot demonstrations are task data, not technique data, so they are
    #: supplied per request and merged with any recipe defaults.
    exemplars: list[Exemplar] = Field(default_factory=list)


class RunRequest(CompileRequest):
    timeout_seconds: float = Field(default=120, gt=0, le=1800)


class DescriptionRequest(BaseModel):
    description: str = Field(min_length=3)
    model: ModelProfile = Field(default_factory=ModelProfile)
    overrides: dict[str, Any] = Field(default_factory=dict)
