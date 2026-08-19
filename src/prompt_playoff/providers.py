from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from typing import Protocol

import httpx
from pydantic import BaseModel

from prompt_playoff.domain import CompiledPrompt, ModelProfile, ModelResult


class ProviderError(RuntimeError):
    pass


class ModelProvider(Protocol):
    async def generate(
        self,
        prompt: CompiledPrompt,
        model: ModelProfile,
        timeout_seconds: float = 120,
    ) -> ModelResult: ...


OLLAMA_DEFAULT_URL = "http://127.0.0.1:11434"


class InstalledModel(BaseModel):
    """One model an Ollama server already holds, as the daemon reports it."""

    model_id: str
    #: "3.2B", "31B" — the daemon's own wording, blank when it does not say.
    parameter_size: str = ""
    size_bytes: int = 0


class ConnectionCheck(BaseModel):
    ok: bool
    provider: str
    model_id: str
    endpoint: str
    latency_seconds: float
    checked_at: str
    detail: str


async def ollama_models(
    base_url: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    timeout_seconds: float = 10,
) -> list[InstalledModel]:
    """What this Ollama has pulled, so a model can be picked instead of typed.

    A mistyped model id is otherwise found only when a benchmark starts and the
    first call fails — after the run has been set up and paid for.
    """
    root = (base_url or OLLAMA_DEFAULT_URL).rstrip("/")
    async with httpx.AsyncClient(timeout=timeout_seconds, transport=transport) as client:
        try:
            response = await client.get(f"{root}/api/tags")
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"Ollama at {root} did not answer: {_reason(exc)}. Start it with `ollama serve`, "
                "or set the base URL of the machine running it."
            ) from exc

    entries = response.json().get("models") or []
    models = [
        InstalledModel(
            model_id=str(entry.get("name") or entry.get("model") or ""),
            parameter_size=str((entry.get("details") or {}).get("parameter_size") or ""),
            size_bytes=int(entry.get("size") or 0),
        )
        for entry in entries
        if isinstance(entry, dict)
    ]
    return sorted((model for model in models if model.model_id), key=lambda item: item.model_id)


async def check_model_connection(
    model: ModelProfile,
    transport: httpx.AsyncBaseTransport | None = None,
    timeout_seconds: float = 10,
) -> ConnectionCheck:
    """Verify credentials, endpoint reachability, and model availability without generation."""
    started = time.perf_counter()
    if model.provider == "ollama":
        endpoint = (model.base_url or OLLAMA_DEFAULT_URL).rstrip("/")
        models = await ollama_models(endpoint, transport=transport, timeout_seconds=timeout_seconds)
        available = {item.model_id for item in models}
        if model.model_id not in available:
            raise ProviderError(
                f"Ollama answered, but model {model.model_id!r} is not installed. "
                f"Available: {', '.join(sorted(available)) or 'none'}"
            )
        detail = f"Ollama is reachable and {model.model_id!r} is installed"
    else:
        endpoint = (model.base_url or PROVIDER_BASE_URLS.get(model.provider) or "").rstrip("/")
        if not endpoint:
            raise ProviderError(f"Provider {model.provider!r} needs model.base_url")
        api_key, _ = resolve_api_key(model)
        headers = {"Authorization": f"Bearer {api_key}"}
        if model.provider == "anthropic":
            headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
        async with httpx.AsyncClient(timeout=timeout_seconds, transport=transport) as client:
            try:
                response = await client.get(f"{endpoint}/v1/models", headers=headers)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise ProviderError(
                    f"Provider connection check failed at {endpoint}: {_reason(exc)}"
                ) from exc
        ids = {
            str(item.get("id"))
            for item in (response.json().get("data") or [])
            if isinstance(item, dict) and item.get("id")
        }
        if ids and model.model_id not in ids:
            raise ProviderError(f"Provider answered, but model {model.model_id!r} was not listed")
        detail = f"Provider credentials and model catalog are reachable for {model.model_id!r}"
    return ConnectionCheck(
        ok=True,
        provider=model.provider,
        model_id=model.model_id,
        endpoint=endpoint,
        latency_seconds=round(time.perf_counter() - started, 4),
        checked_at=datetime.now(UTC).isoformat(timespec="seconds"),
        detail=detail,
    )


async def embed_texts(
    model: ModelProfile,
    texts: list[str],
    transport: httpx.AsyncBaseTransport | None = None,
    timeout_seconds: float = 120,
) -> list[list[float]]:
    """Vectors for a list of texts, from an embedding model on Ollama.

    An embedding model writes nothing; it only says how close two texts are. So
    this is the one model call in the app that cannot invent an answer, which is
    why the dataset checks are allowed to use it and still call themselves
    deterministic: pin the model and the same rows give the same verdict.

    OpenAI-compatible providers have their own `/v1/embeddings` and are not
    wired here yet — a caller that asks for one gets a clear refusal rather than
    a wrong endpoint.
    """
    if not texts:
        return []
    if model.provider != "ollama":
        raise ProviderError(
            f"Embeddings are only wired for Ollama, not {model.provider}. "
            "Point the similarity model at a local Ollama, or leave it blank."
        )
    root = (model.base_url or OLLAMA_DEFAULT_URL).rstrip("/")
    async with httpx.AsyncClient(timeout=timeout_seconds, transport=transport) as client:
        try:
            response = await client.post(
                f"{root}/api/embed", json={"model": model.model_id, "input": texts}
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(f"Embedding request failed: {_reason(exc)}") from exc

    vectors = response.json().get("embeddings") or []
    if len(vectors) != len(texts):
        raise ProviderError(
            f"{model.model_id} returned {len(vectors)} vectors for {len(texts)} rows. "
            "That model may not be an embedding model."
        )
    return [[float(value) for value in vector] for vector in vectors]


class OllamaProvider:
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or OLLAMA_DEFAULT_URL).rstrip("/")

    async def generate(
        self,
        prompt: CompiledPrompt,
        model: ModelProfile,
        timeout_seconds: float = 120,
    ) -> ModelResult:
        payload: dict = {
            "model": model.model_id,
            "messages": [message.wire() for message in prompt.messages],
            "stream": False,
            "options": prompt.generation_options,
        }
        if prompt.response_schema:
            payload["format"] = prompt.response_schema
        if prompt.tools:
            payload["tools"] = prompt.tools
        if prompt.think is not None:
            payload["think"] = prompt.think

        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            try:
                response = await client.post(f"{self.base_url}/api/chat", json=payload)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise ProviderError(f"Ollama request failed: {_reason(exc)}") from exc

        data = response.json()
        message = data.get("message", {})
        usage = {
            key: data[key]
            for key in (
                "total_duration",
                "load_duration",
                "prompt_eval_count",
                "prompt_eval_duration",
                "eval_count",
                "eval_duration",
            )
            if key in data
        }
        return ModelResult(
            content=message.get("content", ""),
            thinking=message.get("thinking"),
            tool_calls=message.get("tool_calls", []),
            usage=usage,
            raw=data,
        )


class OpenAICompatibleProvider:
    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        provider_id: str = "openai",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.provider_id = provider_id
        self.transport = transport

    async def generate(
        self,
        prompt: CompiledPrompt,
        model: ModelProfile,
        timeout_seconds: float = 120,
    ) -> ModelResult:
        payload: dict = {
            "model": model.model_id,
            "messages": [message.wire() for message in prompt.messages],
            "temperature": prompt.generation_options.get("temperature", 0.1),
        }
        if prompt.response_schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "prompt_playoff_response",
                    "strict": True,
                    "schema": prompt.response_schema,
                },
            }
        if prompt.tools:
            payload["tools"] = prompt.tools

        headers = {"Content-Type": "application/json"}
        if self.provider_id == "anthropic":
            headers["x-api-key"] = self.api_key or ""
            headers["anthropic-version"] = "2023-06-01"
        elif self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        async with httpx.AsyncClient(timeout=timeout_seconds, transport=self.transport) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/v1/chat/completions",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise ProviderError(f"OpenAI-compatible request failed: {_reason(exc)}") from exc

        data = response.json()
        message = data.get("choices", [{}])[0].get("message", {})
        return ModelResult(
            content=message.get("content", ""),
            tool_calls=message.get("tool_calls", []),
            usage=data.get("usage", {}),
            raw=data,
        )


def _reason(exc: httpx.HTTPError) -> str:
    """httpx timeouts stringify to an empty message, which reads as no error at all."""
    return str(exc) or type(exc).__name__


PROVIDER_API_KEY_ENVS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "together": "TOGETHER_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "groq": "GROQ_API_KEY",
    "fireworks": "FIREWORKS_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}

PROVIDER_BASE_URLS = {
    "openai": "https://api.openai.com",
    "anthropic": "https://api.anthropic.com",
    "together": "https://api.together.xyz",
    "openrouter": "https://openrouter.ai/api",
    "groq": "https://api.groq.com/openai",
    "fireworks": "https://api.fireworks.ai/inference",
    "deepseek": "https://api.deepseek.com",
}


def resolve_api_key(model: ModelProfile) -> tuple[str, str]:
    """Resolve secrets at the provider boundary so profiles and traces contain only names."""
    if model.api_key is not None:
        value = model.api_key.get_secret_value()
        if value:
            return value, "request"
    candidates = [model.api_key_env, PROVIDER_API_KEY_ENVS.get(model.provider)]
    candidates.append("PROMPT_PLAYOFF_API_KEY")
    checked: list[str] = []
    for name in candidates:
        if not name or name in checked:
            continue
        checked.append(name)
        value = os.environ.get(name)
        if value:
            return value, name
    expected = checked[0]
    suffix = f" (also checked {', '.join(checked[1:])})" if len(checked) > 1 else ""
    raise ProviderError(
        f"Missing API key: set {expected}{suffix} before using provider {model.provider!r}"
    )


def provider_for(model: ModelProfile) -> ModelProvider:
    if model.provider == "ollama":
        return OllamaProvider(model.base_url)
    base_url = model.base_url or PROVIDER_BASE_URLS.get(model.provider)
    if not base_url:
        raise ProviderError(
            f"Provider {model.provider!r} needs model.base_url for its OpenAI-compatible endpoint"
        )
    api_key, _ = resolve_api_key(model)
    return OpenAICompatibleProvider(
        base_url=base_url,
        api_key=api_key,
        provider_id=model.provider,
    )
