"""Optional integrations. Each one imports its third-party dependency lazily so
the core package keeps working when the extra is not installed."""

from __future__ import annotations


class IntegrationError(RuntimeError):
    """Raised when an integration is used without its optional dependency."""


def require(module: str, extra: str) -> None:
    import importlib.util

    if importlib.util.find_spec(module) is None:
        raise IntegrationError(
            f"This feature needs the optional dependency {module!r}. "
            f"Install it with: pip install 'prompt-selector[{extra}]'"
        )
