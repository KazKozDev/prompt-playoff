"""Tracing for real model calls, and dataset import from what was traced.

Two backends behind one interface:

* **Langfuse** — hosted or self-hosted, and the only one here that can also
  *read* production traces back out, which is what turns observed traffic into a
  benchmark dataset.
* **Phoenix / OTLP** — any OpenTelemetry collector, using OpenInference span
  conventions so Phoenix renders the calls as LLM spans.

Tracing wraps the provider, so it captures exactly what was sent and what came
back — including every call of a multi-call technique, individually.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Protocol

from prompt_selector.domain import CompiledPrompt, ModelProfile, ModelResult
from prompt_selector.integrations import require
from prompt_selector.providers import ModelProvider


@dataclass
class CallEvent:
    prompt: CompiledPrompt
    model: ModelProfile
    result: ModelResult
    latency_seconds: float
    prompt_tokens: int
    completion_tokens: int
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class Tracer(Protocol):
    def record(self, event: CallEvent) -> None: ...
    def flush(self) -> None: ...


class NullTracer:
    def record(self, event: CallEvent) -> None:  # noqa: D102
        return None

    def flush(self) -> None:  # noqa: D102
        return None


class TracingProvider:
    """Wraps any provider so every call is traced without changing call sites."""

    def __init__(
        self, inner: ModelProvider, tracer: Tracer, metadata: dict[str, Any] | None = None
    ):
        self.inner = inner
        self.tracer = tracer
        self.metadata = metadata or {}

    async def generate(
        self,
        prompt: CompiledPrompt,
        model: ModelProfile,
        timeout_seconds: float = 120,
    ) -> ModelResult:
        import time

        started = time.perf_counter()
        try:
            result = await self.inner.generate(prompt, model, timeout_seconds)
        except Exception as exc:
            self.tracer.record(
                CallEvent(
                    prompt=prompt,
                    model=model,
                    result=ModelResult(content=""),
                    latency_seconds=round(time.perf_counter() - started, 4),
                    prompt_tokens=0,
                    completion_tokens=0,
                    error=f"{type(exc).__name__}: {exc}",
                    metadata=dict(self.metadata),
                )
            )
            raise

        from prompt_selector.strategies import normalize_usage

        prompt_tokens, completion_tokens = normalize_usage(result.usage)
        self.tracer.record(
            CallEvent(
                prompt=prompt,
                model=model,
                result=result,
                latency_seconds=round(time.perf_counter() - started, 4),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                metadata=dict(self.metadata),
            )
        )
        return result


class LangfuseTracer:
    """Records each call as a Langfuse generation, tagged with the technique."""

    def __init__(
        self,
        public_key: str | None = None,
        secret_key: str | None = None,
        host: str | None = None,
        session_id: str | None = None,
    ) -> None:
        require("langfuse", "tracing")
        from langfuse import Langfuse

        self.client = Langfuse(
            public_key=public_key or os.getenv("LANGFUSE_PUBLIC_KEY"),
            secret_key=secret_key or os.getenv("LANGFUSE_SECRET_KEY"),
            host=host or os.getenv("LANGFUSE_HOST") or "https://cloud.langfuse.com",
        )
        self.session_id = session_id

    def record(self, event: CallEvent) -> None:
        with self.client.start_as_current_observation(
            as_type="generation",
            name=f"{event.prompt.technique_id}:{event.prompt.stage}",
            model=event.model.model_id,
            input=[message.model_dump() for message in event.prompt.messages],
            model_parameters={
                key: value
                for key, value in event.prompt.generation_options.items()
                if isinstance(value, (str, int, float, bool))
            },
            metadata={
                "technique_id": event.prompt.technique_id,
                "stage": event.prompt.stage,
                "provider": event.model.provider,
                "validators": event.prompt.validators,
                "latency_seconds": event.latency_seconds,
                **event.metadata,
            },
        ) as span:
            span.update(
                output=event.result.content,
                usage_details={
                    "input": event.prompt_tokens,
                    "output": event.completion_tokens,
                    "total": event.prompt_tokens + event.completion_tokens,
                },
                level="ERROR" if event.error else "DEFAULT",
                status_message=event.error,
            )
            if self.session_id:
                span.update_trace(session_id=self.session_id)

    def flush(self) -> None:
        self.client.flush()


class OTLPTracer:
    """Emits OpenInference LLM spans to any OTLP collector, Phoenix included."""

    def __init__(
        self,
        endpoint: str | None = None,
        project_name: str = "prompt-selector",
        headers: dict[str, str] | None = None,
        timeout: int = 10,
    ) -> None:
        require("opentelemetry.sdk", "tracing")
        from opentelemetry import trace as otel_trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        endpoint = (
            endpoint
            or os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
            or "http://127.0.0.1:6006/v1/traces"
        )
        provider = TracerProvider(
            resource=Resource.create(
                {"service.name": project_name, "openinference.project.name": project_name}
            )
        )
        provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(endpoint=endpoint, headers=headers or {}, timeout=timeout)
            )
        )
        self.provider = provider
        self.tracer = otel_trace.get_tracer(__name__, tracer_provider=provider)

    def record(self, event: CallEvent) -> None:
        name = f"{event.prompt.technique_id}:{event.prompt.stage}"
        with self.tracer.start_as_current_span(name) as span:
            span.set_attribute("openinference.span.kind", "LLM")
            span.set_attribute("llm.model_name", event.model.model_id)
            span.set_attribute("llm.provider", event.model.provider)
            span.set_attribute("llm.token_count.prompt", event.prompt_tokens)
            span.set_attribute("llm.token_count.completion", event.completion_tokens)
            span.set_attribute(
                "llm.token_count.total", event.prompt_tokens + event.completion_tokens
            )
            span.set_attribute("prompt_selector.technique_id", event.prompt.technique_id)
            span.set_attribute("prompt_selector.stage", event.prompt.stage)
            span.set_attribute("prompt_selector.latency_seconds", event.latency_seconds)
            for index, message in enumerate(event.prompt.messages):
                span.set_attribute(f"llm.input_messages.{index}.message.role", message.role)
                span.set_attribute(f"llm.input_messages.{index}.message.content", message.content)
            span.set_attribute("llm.output_messages.0.message.role", "assistant")
            span.set_attribute("llm.output_messages.0.message.content", event.result.content)
            if event.error:
                span.set_attribute("error.message", event.error)

    def flush(self) -> None:
        self.provider.force_flush()


def build_tracer(backend: str, **kwargs: Any) -> Tracer:
    backend = (backend or "none").lower()
    if backend in {"none", "off", ""}:
        return NullTracer()
    if backend == "langfuse":
        return LangfuseTracer(**kwargs)
    if backend in {"phoenix", "otlp"}:
        return OTLPTracer(**kwargs)
    raise ValueError(f"Unknown tracing backend {backend!r}. Known: none, langfuse, phoenix")


def tracer_from_env() -> Tracer:
    """Enabled by PROMPT_SELECTOR_TRACING=langfuse|phoenix, off by default."""
    return build_tracer(os.getenv("PROMPT_SELECTOR_TRACING", "none"))


# --------------------------------------------------------------------------- #
# traces -> dataset
# --------------------------------------------------------------------------- #


def import_langfuse_dataset(
    limit: int = 100,
    technique_id: str | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
    tags: list[str] | None = None,
    include_output_as_expected: bool = False,
    public_key: str | None = None,
    secret_key: str | None = None,
    host: str | None = None,
) -> list[dict[str, Any]]:
    """Turn observed production calls into benchmark examples.

    ``include_output_as_expected`` records what the model produced as the gold
    answer. That is only honest when the traffic was reviewed — otherwise you
    are benchmarking a model against its own past mistakes. Left off by default;
    the examples come back with an empty ``expected`` for a human to fill in.
    """
    require("langfuse", "tracing")
    from langfuse import Langfuse

    client = Langfuse(
        public_key=public_key or os.getenv("LANGFUSE_PUBLIC_KEY"),
        secret_key=secret_key or os.getenv("LANGFUSE_SECRET_KEY"),
        host=host or os.getenv("LANGFUSE_HOST") or "https://cloud.langfuse.com",
    )
    response = client.api.observations.get_many(
        type="GENERATION",
        limit=min(limit, 100),
        user_id=user_id,
        **({"trace_tags": tags} if tags else {}),
    )

    examples: list[dict[str, Any]] = []
    seen: set[str] = set()
    for observation in getattr(response, "data", []) or []:
        metadata = getattr(observation, "metadata", None) or {}
        if technique_id and metadata.get("technique_id") != technique_id:
            continue
        if session_id and getattr(observation, "session_id", None) != session_id:
            continue
        user_text = _user_message(getattr(observation, "input", None))
        if not user_text:
            continue
        key = user_text[:400]
        if key in seen:
            continue
        seen.add(key)

        example: dict[str, Any] = {
            "id": str(getattr(observation, "id", f"trace-{len(examples) + 1}")),
            "input": user_text,
            "expected": None,
            "tags": ["imported", "unreviewed"],
        }
        if include_output_as_expected:
            output = getattr(observation, "output", None)
            parsed = _maybe_json(output)
            if parsed is not None:
                example["expected"] = parsed
                example["tags"] = ["imported", "output-as-expected"]
        examples.append(example)
        if len(examples) >= limit:
            break
    return examples


def write_jsonl(path, examples: list[dict[str, Any]]) -> int:
    from pathlib import Path

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for example in examples:
            handle.write(json.dumps(example, ensure_ascii=False) + "\n")
    return len(examples)


def _user_message(payload: Any) -> str | None:
    if isinstance(payload, list):
        for message in reversed(payload):
            if isinstance(message, dict) and message.get("role") == "user":
                return str(message.get("content", "")).strip() or None
        return None
    if isinstance(payload, dict):
        for key in ("input", "content", "prompt"):
            if key in payload:
                return str(payload[key]).strip() or None
        return None
    if isinstance(payload, str):
        return payload.strip() or None
    return None


def _maybe_json(payload: Any) -> Any | None:
    if payload is None:
        return None
    if isinstance(payload, (dict, list)):
        return payload
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return payload.strip() or None
    return None
