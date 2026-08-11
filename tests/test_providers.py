import json

import httpx
import pytest

from prompt_selector.domain import CompiledPrompt, Message, ModelProfile, ModelResult
from prompt_selector.integrations.tracing import TracingProvider
from prompt_selector.providers import OpenAICompatibleProvider, ProviderError, provider_for


def test_openai_provider_reads_api_key_from_environment(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "environment-only-secret")
    model = ModelProfile(
        provider="openai",
        model_id="gpt-test",
        base_url="https://api.openai.test",
    )

    provider = provider_for(model)

    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.api_key == "environment-only-secret"


def test_request_api_key_takes_precedence_and_never_serializes(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "environment-secret")
    model = ModelProfile(
        provider="openai",
        model_id="gpt-test",
        api_key="request-only-secret",
    )

    provider = provider_for(model)

    assert provider.api_key == "request-only-secret"  # type: ignore[attr-defined]
    assert "request-only-secret" not in repr(model)
    assert "api_key" not in model.model_dump()
    assert "request-only-secret" not in model.model_dump_json()


def test_generic_compatible_provider_uses_shared_fallback(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-only-secret")
    monkeypatch.setenv("PROMPT_SELECTOR_API_KEY", "compatible-secret")
    model = ModelProfile(
        provider="custom",
        model_id="compatible-test",
        base_url="https://compatible.example",
    )

    provider = provider_for(model)

    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.api_key == "compatible-secret"


@pytest.mark.parametrize(
    ("provider_id", "env_name"),
    [
        ("openai", "OPENAI_API_KEY"),
        ("anthropic", "ANTHROPIC_API_KEY"),
        ("together", "TOGETHER_API_KEY"),
        ("openrouter", "OPENROUTER_API_KEY"),
        ("groq", "GROQ_API_KEY"),
        ("fireworks", "FIREWORKS_API_KEY"),
        ("deepseek", "DEEPSEEK_API_KEY"),
    ],
)
def test_provider_default_key_environment(monkeypatch, provider_id, env_name):
    monkeypatch.setenv(env_name, f"{provider_id}-secret")
    provider = provider_for(ModelProfile(provider=provider_id, model_id="test"))
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.api_key == f"{provider_id}-secret"


def test_key_precedence_is_explicit_then_provider_then_shared(monkeypatch):
    monkeypatch.setenv("MY_TEAM_KEY", "explicit")
    monkeypatch.setenv("TOGETHER_API_KEY", "provider")
    monkeypatch.setenv("PROMPT_SELECTOR_API_KEY", "shared")
    model = ModelProfile(provider="together", model_id="test", api_key_env="MY_TEAM_KEY")
    assert provider_for(model).api_key == "explicit"  # type: ignore[attr-defined]
    monkeypatch.delenv("MY_TEAM_KEY")
    assert provider_for(model).api_key == "provider"  # type: ignore[attr-defined]
    monkeypatch.delenv("TOGETHER_API_KEY")
    assert provider_for(model).api_key == "shared"  # type: ignore[attr-defined]


def test_missing_key_fails_before_a_request_and_names_the_fix(monkeypatch):
    for name in ("OPENROUTER_API_KEY", "PROMPT_SELECTOR_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ProviderError, match="OPENROUTER_API_KEY"):
        provider_for(ModelProfile(provider="openrouter", model_id="test"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider_id", ["openai", "together", "openrouter", "groq", "fireworks", "deepseek"]
)
async def test_compatible_providers_send_bearer_auth(provider_id):
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    provider = OpenAICompatibleProvider(
        "https://provider.test",
        "header-secret",
        provider_id=provider_id,
        transport=httpx.MockTransport(respond),
    )
    await provider.generate(_prompt(), ModelProfile(provider=provider_id, model_id="test"))
    assert seen[0].headers["Authorization"] == "Bearer header-secret"
    assert "x-api-key" not in seen[0].headers


@pytest.mark.asyncio
async def test_anthropic_uses_its_header_shape_without_bearer_auth():
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    provider = OpenAICompatibleProvider(
        "https://anthropic.test",
        "anthropic-secret",
        provider_id="anthropic",
        transport=httpx.MockTransport(respond),
    )
    await provider.generate(_prompt(), ModelProfile(provider="anthropic", model_id="test"))
    assert seen[0].headers["x-api-key"] == "anthropic-secret"
    assert seen[0].headers["anthropic-version"] == "2023-06-01"
    assert "Authorization" not in seen[0].headers


@pytest.mark.asyncio
async def test_api_key_never_enters_traced_events():
    class SecretProvider:
        api_key = "never-trace-this-secret"

        async def generate(self, prompt, model, timeout_seconds=120):
            return ModelResult(content="ok", raw={"response": "safe"})

    class RecordingTracer:
        def __init__(self):
            self.events = []

        def record(self, event):
            self.events.append(event)

        def flush(self):
            return None

    tracer = RecordingTracer()
    provider = TracingProvider(SecretProvider(), tracer)
    result = await provider.generate(_prompt(), ModelProfile(provider="openai", model_id="test"))
    assert "never-trace-this-secret" not in repr(tracer.events)
    assert "never-trace-this-secret" not in json.dumps(result.raw)


def _prompt() -> CompiledPrompt:
    return CompiledPrompt(
        technique_id="test",
        stage="single",
        messages=[Message(role="user", content="hello")],
    )
