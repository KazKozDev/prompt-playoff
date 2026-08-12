from __future__ import annotations

import asyncio
import json

import pytest
import yaml
from conftest import FakeProvider

from prompt_playoff.checks import CheckConfigError, load_check_file, run_checks
from prompt_playoff.providers import ProviderError


class UnreachableProvider:
    async def generate(self, prompt, model, timeout_seconds=120):
        raise ProviderError("connection refused")


def _files(tmp_path, *, technique="structured.schema-first", require=None):
    dataset = tmp_path / "one.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "id": "one",
                "input": "Mara entered Veyr.",
                "expected": {"people": ["Mara"], "places": ["Veyr"]},
                "response_schema": {
                    "type": "object",
                    "properties": {
                        "people": {"type": "array", "items": {"type": "string"}},
                        "places": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["people", "places"],
                    "additionalProperties": False,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    config = tmp_path / "prompt-playoff.yaml"
    payload = {
        "version": 1,
        "model": {
            "provider": "ollama",
            "model_id": "fake",
            "model_class": "small",
            "capabilities": ["structured_output", "system_messages"],
        },
        "checks": [
            {
                "name": "entities",
                "technique": technique,
                "task": "structured_extraction",
                "dataset_file": "./one.jsonl",
                "repeats": 1,
                "strict_json": True,
                "require": require or {"quality_min": 0.9, "reliability_min": 0.9},
            }
        ],
    }
    config.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return config


def test_passing_check_exits_zero(tmp_path):
    result = asyncio.run(
        run_checks(_files(tmp_path), provider_factory=lambda model: FakeProvider())
    )
    assert result.exit_code == 0
    assert result.checks[0].status == "passed"


def test_breached_bound_exits_one_and_names_field(tmp_path):
    config = _files(tmp_path, require={"mean_total_tokens_max": 100})
    result = asyncio.run(run_checks(config, provider_factory=lambda model: FakeProvider()))
    assert result.exit_code == 1
    failed = result.checks[0].thresholds[0]
    assert failed.field == "mean_total_tokens"
    assert not failed.passed
    assert failed.difference == 20


def test_unknown_technique_exits_two(tmp_path):
    config = _files(tmp_path, technique="does.not-exist")
    result = asyncio.run(run_checks(config, provider_factory=lambda model: FakeProvider()))
    assert result.exit_code == 2
    assert "does.not-exist" in (result.checks[0].error or "")


def test_unreachable_provider_exits_two_not_one(tmp_path):
    config = _files(tmp_path)
    result = asyncio.run(run_checks(config, provider_factory=lambda model: UnreachableProvider()))
    assert result.exit_code == 2
    assert "connection refused" in (result.checks[0].error or "")


def test_update_preserves_comments_and_writes_thresholds_that_pass(tmp_path):
    config = _files(tmp_path, require={"quality_min": 2, "mean_total_tokens_max": 1})
    text = config.read_text(encoding="utf-8").replace(
        "quality_min: 2", "quality_min: 2  # reviewed baseline"
    )
    config.write_text(text, encoding="utf-8")
    updated = asyncio.run(
        run_checks(config, update=True, provider_factory=lambda model: FakeProvider())
    )
    assert updated.exit_code == 0
    assert updated.updated
    assert "# reviewed baseline" in config.read_text(encoding="utf-8")
    rerun = asyncio.run(run_checks(config, provider_factory=lambda model: FakeProvider()))
    assert rerun.exit_code == 0


def test_all_checks_run_after_one_setup_error(tmp_path):
    config = _files(tmp_path)
    payload = yaml.safe_load(config.read_text(encoding="utf-8"))
    payload["checks"].insert(0, {**payload["checks"][0], "name": "bad", "technique": "bad"})
    config.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    result = asyncio.run(run_checks(config, provider_factory=lambda model: FakeProvider()))
    assert [item.status for item in result.checks] == ["error", "passed"]
    assert result.exit_code == 2


@pytest.mark.parametrize(
    ("requirements", "message"),
    [({}, "at least one"), ({"quality_greater_than": 0.9}, "valid keys")],
)
def test_invalid_require_blocks_name_the_configuration_fix(tmp_path, requirements, message):
    config = _files(tmp_path)
    payload = yaml.safe_load(config.read_text(encoding="utf-8"))
    payload["checks"][0]["require"] = requirements
    config.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    with pytest.raises(CheckConfigError, match=message):
        load_check_file(config)
