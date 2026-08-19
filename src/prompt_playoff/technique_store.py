"""On-disk home for techniques produced by optimization rather than by the registry.

An optimization run costs real model calls, and its winner is a technique file:
`export_technique` already emits one, and the CLI has always been able to write
it with `optimize --export`. Until it is somewhere the server can resolve, that
file is a document — `/v1/run` and the runtime export both work from a technique
id, so a winner that lives only in a download cannot actually be run.

Each technique is one YAML file, the same format the packaged recipes use, so a
saved winner can be read, edited, copied, deleted or committed to a registry of
your own with ordinary tools. The id lives in the filename, percent-encoded: ids
carry `.`, which is fine, and nothing else here is guaranteed to be.

These are deliberately not part of ranking. A technique optimized against one
dataset for one task is not evidence about anybody else's task, and putting it
in the selector's population would let it win recommendations it was never
measured for. It is resolvable by id, and that is all.
"""

from __future__ import annotations

import os
import urllib.parse
from pathlib import Path

import yaml
from pydantic import ValidationError

from prompt_playoff.domain import TechniqueSpec
from prompt_playoff.persistence import atomic_write_text, quarantine_corrupt_file

DEFAULT_DIR = Path("benchmark-results/techniques")

_SAFE = "-._"


def encode_id(technique_id: str) -> str:
    return urllib.parse.quote(technique_id, safe=_SAFE)


def decode_id(filename: str) -> str:
    return urllib.parse.unquote(filename)


def to_yaml(payload: dict) -> str:
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, width=100)


class TechniqueStore:
    """Reads and writes optimized techniques as YAML files in one directory."""

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory if directory is not None else _default_dir()
        #: Files that no longer parse, kept for the caller to report.
        self.corrupt: list[Path] = []

    def path_for(self, technique_id: str) -> Path:
        return self.directory / f"{encode_id(technique_id)}.yaml"

    def load(self) -> dict[str, TechniqueSpec]:
        """Every saved technique, skipping any file that no longer parses.

        One bad file must not stop the server from starting: it is moved aside
        like a corrupt measurement store and listed in :attr:`corrupt`.
        """
        self.corrupt = []
        if not self.directory.is_dir():
            return {}
        loaded: dict[str, TechniqueSpec] = {}
        for path in sorted(self.directory.glob("*.yaml")):
            try:
                spec = TechniqueSpec.model_validate(yaml.safe_load(path.read_text("utf-8")))
            except (OSError, yaml.YAMLError, ValidationError):
                try:
                    self.corrupt.append(quarantine_corrupt_file(path))
                except OSError:
                    self.corrupt.append(path)
                continue
            loaded[spec.id] = spec
        return loaded

    @property
    def recovery_warning(self) -> str | None:
        if not self.corrupt:
            return None
        moved = ", ".join(str(path) for path in self.corrupt)
        return f"Unreadable saved techniques were moved to {moved}"

    def save(self, spec: TechniqueSpec) -> Path:
        path = self.path_for(spec.id)
        atomic_write_text(path, to_yaml(spec.model_dump(mode="json")))
        return path

    def remove(self, technique_id: str) -> bool:
        try:
            self.path_for(technique_id).unlink()
        except FileNotFoundError:
            return False
        return True


def _default_dir() -> Path:
    custom = os.getenv("PROMPT_PLAYOFF_TECHNIQUES")
    if custom:
        return Path(custom).expanduser()
    return DEFAULT_DIR
