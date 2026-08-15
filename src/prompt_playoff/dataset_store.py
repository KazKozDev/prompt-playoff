"""On-disk home for datasets brought in from outside the package.

A dataset imported from the Hugging Face Hub costs a download and a set of
column decisions the user had to make by hand. Losing that to a server restart
means making the same decisions again, so the rows are written next to the
measurements they will produce.

Each dataset is one JSONL file, the same format the packaged datasets and the
upload endpoint already use, so a saved file can be read, edited, copied or
deleted with ordinary tools. The name lives in the filename, percent-encoded:
dataset names carry ``:`` and ``/``, which are not filename characters, and an
encoding that round-trips is one less index file to keep consistent.
"""

from __future__ import annotations

import os
import urllib.parse
from pathlib import Path

from prompt_playoff.evals import BenchmarkExample, load_jsonl
from prompt_playoff.persistence import atomic_write_text, quarantine_corrupt_file

DEFAULT_DIR = Path("benchmark-results/datasets")

#: Filenames stay ASCII and shell-safe; everything else is percent-encoded.
_SAFE = "-._"


def encode_name(name: str) -> str:
    return urllib.parse.quote(name, safe=_SAFE)


def decode_name(filename: str) -> str:
    return urllib.parse.unquote(filename)


class DatasetStore:
    """Reads and writes the user's own datasets as JSONL files in one directory."""

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory if directory is not None else _default_dir()
        #: Files that could not be parsed, kept for the caller to report.
        self.corrupt: list[Path] = []

    def path_for(self, name: str) -> Path:
        return self.directory / f"{encode_name(name)}.jsonl"

    def load(self) -> dict[str, list[BenchmarkExample]]:
        """Every saved dataset, skipping any file that no longer parses.

        A single bad file must not stop the server from starting: it is moved
        aside like a corrupt measurement store and listed in :attr:`corrupt`.
        """
        self.corrupt = []
        if not self.directory.is_dir():
            return {}
        loaded: dict[str, list[BenchmarkExample]] = {}
        for path in sorted(self.directory.glob("*.jsonl")):
            try:
                examples = load_jsonl(path)
            except (OSError, ValueError):
                try:
                    self.corrupt.append(quarantine_corrupt_file(path))
                except OSError:
                    self.corrupt.append(path)
                continue
            if examples:
                loaded[decode_name(path.stem)] = examples
        return loaded

    @property
    def recovery_warning(self) -> str | None:
        if not self.corrupt:
            return None
        moved = ", ".join(str(path) for path in self.corrupt)
        return f"Unreadable saved datasets were moved to {moved}"

    def save(self, name: str, examples: list[BenchmarkExample]) -> Path:
        path = self.path_for(name)
        body = "".join(f"{item.model_dump_json(exclude_defaults=True)}\n" for item in examples)
        atomic_write_text(path, body)
        return path

    def remove(self, name: str) -> bool:
        try:
            self.path_for(name).unlink()
        except FileNotFoundError:
            return False
        return True


def _default_dir() -> Path:
    custom = os.getenv("PROMPT_PLAYOFF_DATASETS")
    if custom:
        return Path(custom).expanduser()
    return DEFAULT_DIR
