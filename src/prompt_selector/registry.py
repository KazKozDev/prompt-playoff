from __future__ import annotations

import os
from importlib.resources import files
from pathlib import Path

import yaml
from pydantic import TypeAdapter, ValidationError

from prompt_selector.domain import ModelProfile, TechniqueSpec


class RegistryError(RuntimeError):
    pass


class Registry:
    def __init__(
        self,
        techniques: list[TechniqueSpec],
        models: list[ModelProfile],
        datasets: dict[str, Path] | None = None,
    ) -> None:
        self.techniques = {item.id: item for item in techniques}
        self.models = {(item.provider, item.model_id): item for item in models}
        self.datasets = datasets or {}
        if len(self.techniques) != len(techniques):
            raise RegistryError("Duplicate technique id detected")

    @classmethod
    def load(cls, root: Path | None = None) -> Registry:
        root = root or _default_data_root()
        technique_files = sorted((root / "techniques").glob("*.yaml"))
        model_files = sorted((root / "models").glob("*.yaml"))
        if not technique_files:
            raise RegistryError(f"No technique recipes found under {root / 'techniques'}")

        techniques = [_load_model(path, TechniqueSpec) for path in technique_files]
        models = [_load_model(path, ModelProfile) for path in model_files]
        datasets = {path.stem: path for path in sorted((root / "datasets").glob("*.jsonl"))}
        return cls(techniques=techniques, models=models, datasets=datasets)

    def technique(self, technique_id: str) -> TechniqueSpec:
        try:
            return self.techniques[technique_id]
        except KeyError as exc:
            raise RegistryError(f"Unknown technique: {technique_id}") from exc

    def model(self, provider: str, model_id: str) -> ModelProfile | None:
        return self.models.get((provider, model_id))

    def dataset_path(self, name: str) -> Path:
        try:
            return self.datasets[name]
        except KeyError as exc:
            known = ", ".join(sorted(self.datasets)) or "none"
            raise RegistryError(f"Unknown dataset: {name}. Available: {known}") from exc


def _default_data_root() -> Path:
    custom = os.getenv("PROMPT_SELECTOR_REGISTRY")
    if custom:
        return Path(custom).expanduser().resolve()
    return Path(str(files("prompt_selector").joinpath("data")))


def _load_model(path: Path, model_type):
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        return TypeAdapter(model_type).validate_python(payload)
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise RegistryError(f"Invalid registry file {path}: {exc}") from exc
