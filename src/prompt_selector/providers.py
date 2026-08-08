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
                raise ProviderError(f"Ollama request failed: {exc}") from exc

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
    def __init__(self, base_url: str, api_key: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

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
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/v1/chat/completions",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise ProviderError(f"OpenAI-compatible request failed: {exc}") from exc

        data = response.json()
        message = data.get("choices", [{}])[0].get("message", {})
        return ModelResult(
            content=message.get("content", ""),
            tool_calls=message.get("tool_calls", []),
            usage=data.get("usage", {}),
            raw=data,
        )


def provider_for(model: ModelProfile) -> ModelProvider:
    base_url = model.base_url
    if model.provider == "ollama":
        return OllamaProvider(base_url)
    if not base_url:
        raise ProviderError("OpenAI-compatible models require model.base_url")
    api_key = os.environ.get("OPENAI_API_KEY") if model.provider == "openai" else None
    return OpenAICompatibleProvider(base_url=base_url, api_key=api_key)
