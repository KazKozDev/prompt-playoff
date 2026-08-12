"""Dependency-aware console entry point."""

from __future__ import annotations


def main() -> None:
    try:
        from prompt_playoff.cli import app
    except ModuleNotFoundError as exc:
        if exc.name in {"typer", "rich"}:
            print("CLI dependencies are missing; run: pip install 'prompt-playoff[cli]'")
            raise SystemExit(1) from None
        raise
    app()
