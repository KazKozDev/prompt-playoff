"""Dependency-aware console entry point."""

from __future__ import annotations


def main() -> None:
    # A checked-in .env.example is useful only if the launcher follows it.
    # python-dotenv does not override variables already exported by the shell,
    # so deployment configuration keeps precedence over local convenience.
    from dotenv import load_dotenv

    load_dotenv()
    try:
        from prompt_playoff.cli import app
    except ModuleNotFoundError as exc:
        if exc.name in {"typer", "rich"}:
            print("CLI dependencies are missing; run: pip install 'prompt-playoff[cli]'")
            raise SystemExit(1) from None
        raise
    app()
