from prompt_selector.registry import Registry


def test_registry_loads() -> None:
    registry = Registry.load()
    assert len(registry.techniques) >= 14
    assert "structured.schema-first" in registry.techniques
    assert len(registry.models) >= 3
