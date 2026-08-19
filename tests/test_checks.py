from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
import yaml
from conftest import FakeProvider

from prompt_playoff.checks import (
    CheckConfigError,
    load_check_file,
    release_gate,
    run_checks,
)
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


def test_cost_threshold_uses_explicit_model_prices(tmp_path):
    config = _files(tmp_path, require={"mean_cost_usd_max": 0.001})
    payload = yaml.safe_load(config.read_text(encoding="utf-8"))
    payload["model"]["input_cost_per_million_usd"] = 1
    payload["model"]["output_cost_per_million_usd"] = 10
    config.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    result = asyncio.run(run_checks(config, provider_factory=lambda model: FakeProvider()))

    assert result.exit_code == 0
    assert result.checks[0].thresholds[0].measured == pytest.approx(0.0003)


def test_failed_check_sends_redacted_webhook(tmp_path):
    config = _files(tmp_path, require={"quality_min": 2})
    payload = yaml.safe_load(config.read_text(encoding="utf-8"))
    payload["notifications"] = {"webhook_urls": ["https://alerts.example/private/token?secret=yes"]}
    config.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    received = []

    def handler(request):
        received.append(json.loads(request.content))
        return httpx.Response(204)

    result = asyncio.run(
        run_checks(
            config,
            provider_factory=lambda model: FakeProvider(),
            notification_transport=httpx.MockTransport(handler),
        )
    )

    assert result.exit_code == 1
    assert received[0]["event"] == "prompt_playoff.regression"
    assert result.notifications[0].status == "sent"
    assert "token" not in result.notifications[0].destination
    assert "secret" not in result.notifications[0].destination


def _gate_config(tmp_path: Path, technique: str = "structured.schema-first") -> Path:
    path = tmp_path / "prompt-playoff.yaml"
    path.write_text(
        f"""
version: 1
model:
  provider: ollama
  model_id: llama3.2:3b
checks:
  - name: shipping-bar
    technique: {technique}
    task: structured_extraction
    dataset: entity-extraction
    require:
      quality_min: 0.85
      mean_total_tokens_max: 300
""",
        encoding="utf-8",
    )
    return path


def test_the_release_gate_applies_the_committed_bar_to_a_recorded_run(tmp_path: Path):
    path = _gate_config(tmp_path)
    passed = release_gate(
        "structured.schema-first", {"quality": 0.91, "mean_total_tokens": 250.0}, path
    )
    assert passed.status == "passed"
    assert not passed.blocks_approval
    assert [item.field for item in passed.thresholds] == ["mean_total_tokens", "quality"]

    failed = release_gate(
        "structured.schema-first", {"quality": 0.62, "mean_total_tokens": 250.0}, path
    )
    assert failed.status == "failed"
    assert failed.blocks_approval
    assert "quality 0.62 vs min 0.85" in (failed.reason or "")


def test_a_gate_that_cannot_be_evaluated_is_not_a_gate_that_passed(tmp_path: Path):
    """Three ways to not know, and none of them may read as approval."""
    path = _gate_config(tmp_path)

    unmeasured = release_gate("structured.schema-first", None, path)
    assert unmeasured.status == "unmeasured"
    assert unmeasured.blocks_approval

    # The run is there but carries none of the fields the bar names.
    partial = release_gate("structured.schema-first", {"reliability": 1.0}, path)
    assert partial.status == "unenforceable"
    assert partial.blocks_approval
    assert "mean_total_tokens, quality" in (partial.reason or "")

    broken = tmp_path / "broken.yaml"
    broken.write_text("version: 1\nchecks: []\n", encoding="utf-8")
    assert release_gate("structured.schema-first", {"quality": 1.0}, broken).status == (
        "unenforceable"
    )


def test_no_committed_bar_is_not_a_failure(tmp_path: Path):
    """A gate nobody configured must not block every release in the project."""
    absent = release_gate("direct", {"quality": 0.1}, tmp_path / "missing.yaml")
    assert absent.status == "not_configured"
    assert not absent.blocks_approval

    other = release_gate("direct", {"quality": 0.1}, _gate_config(tmp_path))
    assert other.status == "not_configured"
    assert "commits no thresholds for direct" in (other.reason or "")
