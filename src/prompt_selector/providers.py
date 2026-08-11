from __future__ import annotations

import os
from typing import Protocol

import httpx

from prompt_selector.domain import CompiledPrompt, ModelProfile, ModelResult


class ProviderError(RuntimeError):
    pass


class ModelProvider(Protocol):
    async def generate(
        self,
        prompt: CompiledPrompt,
        model: ModelProfile,
        timeout_seconds: float = 120,
    ) -> ModelResult: ...


class OllamaProvider:
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or "http://127.0.0.1:11434").rstrip("/")

    async def generate(
        self,
        prompt: CompiledPrompt,
        model: ModelProfile,
        timeout_seconds: float = 120,
    ) -> ModelResult:
        payload: dict = {
            "model": model.model_id,
            "messages": [message.model_dump() for message in prompt.messages],
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
            "messages": [message.model_dump() for message in prompt.messages],
            "temperature": prompt.generation_options.get("temperature", 0.1),
        }
        if prompt.response_schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "prompt_selector_response",
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
    candidates.append("PROMPT_SELECTOR_API_KEY")
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
