"""Optional integrations. Each one imports its third-party dependency lazily so
the core package keeps working when the extra is not installed."""

from __future__ import annotations


class IntegrationError(RuntimeError):
    """Raised when an integration is used without its optional dependency."""


def installed(module: str) -> bool:
    """Whether an optional dependency is importable.

    ``find_spec`` imports the parent of a dotted name to read its ``__path__``,
    so asking for ``opentelemetry.sdk`` on a machine without opentelemetry
    raises instead of answering False. Every "is this installed?" question goes
    through here so a missing extra stays a False and never a 500.
    """
    import importlib.util

    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def require(module: str, extra: str) -> None:
    if not installed(module):
        raise IntegrationError(
            f"This feature needs the optional dependency {module!r}. "
            f"Install it with: pip install 'prompt-playoff[{extra}]'"
        )
