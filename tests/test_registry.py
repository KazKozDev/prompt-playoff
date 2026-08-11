from prompt_selector.domain import EvidenceLevel
from prompt_selector.registry import Registry


def test_registry_loads() -> None:
    registry = Registry.load()
    assert len(registry.techniques) >= 14
    assert "structured.schema-first" in registry.techniques
    assert len(registry.models) >= 3


def test_a_cited_paper_can_be_opened() -> None:
    """The Techniques tab links every citation, so a citation needs a URL.

    The lint rule requires a source once evidence_level rises above heuristic,
    but not a link — a technique could arrive naming a paper with no way to
    reach it, and the tab would render dead text next to real links.
    """
    for technique in Registry.load().techniques.values():
        if technique.source is None:
            continue
        url = technique.source.url or ""
        assert url.startswith(("http://", "https://")), (
            f"{technique.id} cites {technique.source.paper!r} with no reachable URL"
        )


def test_an_unsourced_technique_admits_it_is_a_pattern() -> None:
    """The other half of the same claim: no paper means no published evidence."""
    for technique in Registry.load().techniques.values():
        if technique.source is None:
            assert technique.evidence_level is EvidenceLevel.heuristic, (
                f"{technique.id} claims {technique.evidence_level.value} evidence "
                "without naming a source"
            )
