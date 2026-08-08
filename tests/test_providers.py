from prompt_selector.domain import ModelProfile
from prompt_selector.providers import OpenAICompatibleProvider, provider_for


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


def test_generic_compatible_provider_does_not_reuse_openai_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-only-secret")
    model = ModelProfile(
        provider="custom",
        model_id="compatible-test",
        base_url="https://compatible.example",
    )

    provider = provider_for(model)

    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.api_key is None
