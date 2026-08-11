"""The command line as a user meets it.

Every layer under this one is tested elsewhere; what is untested without this
file is the part only the CLI owns — option names, how strings become domain
objects, exit codes, and whether `--json` is machine-readable. A rename in
`_task` or a mistyped option default breaks nothing in the other suites.

These run without a model. Anything needing one is exercised through the fake
provider in `tests/fake_provider_server.py` and the `check` gate in CI.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from prompt_selector import __version__
from prompt_selector.cli import app

runner = CliRunner()


@pytest.fixture
def invoke():
    def run(*args: str, code: int = 0):
        result = runner.invoke(app, list(args))
        assert result.exit_code == code, (
            f"prompt-selector {' '.join(args)}\nexit {result.exit_code}\n{result.output}"
        )
        return result

    return run


# --------------------------------------------------------------------------- #
# the entry point itself
# --------------------------------------------------------------------------- #


def test_version_matches_the_package(invoke):
    assert invoke("--version").output.strip() == __version__


def test_bare_invocation_shows_help_rather_than_doing_something(invoke):
    # no_args_is_help: running the tool with no arguments must not select,
    # compile or call anything.
    output = invoke(code=2).output
    assert "Usage:" in output


@pytest.mark.parametrize(
    "command",
    [
        "recommend",
        "select",
        "select-file",
        "compile",
        "run",
        "benchmark",
        "check",
        "compare",
        "optimize",
        "export-promptfoo",
        "import-traces",
        "import-hf",
        "list-hf-presets",
        "tracing-status",
        "list-techniques",
        "list-datasets",
        "capabilities",
        "validate-registry",
        "new-technique",
        "show-technique",
        "serve",
    ],
)
def test_every_command_is_reachable_and_describes_itself(invoke, command):
    """A command with no help string reads as a bare name in the command list."""
    lines = invoke(command, "--help").output.splitlines()
    usage = next(i for i, line in enumerate(lines) if "Usage:" in line)
    # Everything between the usage line and the first options panel is the
    # description. Splitting on "Usage:" itself would keep the rest of that line
    # and pass for a command that has no description at all.
    body = lines[usage + 1 :]
    end = next((i for i, line in enumerate(body) if line.startswith("╭")), len(body))
    description = "\n".join(body[:end]).strip()
    assert description, f"{command} has no help string"


# --------------------------------------------------------------------------- #
# reading the registry
# --------------------------------------------------------------------------- #


def test_list_techniques_covers_the_whole_registry(invoke):
    from prompt_selector.registry import Registry

    output = invoke("list-techniques").output
    families = {spec.family for spec in Registry.load().techniques.values()}
    # Long ids are truncated in the table, so match on families, which are short.
    for family in families:
        assert family[:8] in output


def test_list_datasets_reports_gold_coverage(invoke):
    output = invoke("list-datasets").output
    assert "entity-extraction" in output
    assert "With expected" in output


def test_capabilities_is_machine_readable(invoke):
    payload = json.loads(invoke("capabilities").output)
    assert payload["strategies"]
    assert payload["graders"]
    assert payload["aggregators"]


def test_show_technique_prints_the_spec(invoke):
    output = invoke("show-technique", "structured.schema-first").output
    assert "schema-first" in output
    assert "blocks" in output


def test_show_technique_fails_on_an_unknown_id(invoke):
    result = runner.invoke(app, ["show-technique", "structured.no-such-technique"])
    assert result.exit_code != 0


def test_validate_registry_passes_on_the_shipped_registry(invoke):
    assert "Registry valid." in invoke("validate-registry").output


def test_validate_registry_strict_also_passes(invoke):
    """The registry ships clean of warnings, and CI runs --strict."""
    invoke("validate-registry", "--strict")


# --------------------------------------------------------------------------- #
# selection: the options are the part only this layer defines
# --------------------------------------------------------------------------- #


def test_select_ranks_and_explains(invoke):
    output = invoke("select", "--task", "structured_extraction", "--model", "qwen2.5:7b").output
    assert "Rank" in output


def test_select_json_is_parseable_and_carries_reasons(invoke):
    payload = json.loads(
        invoke(
            "select",
            "--task",
            "structured_extraction",
            "--model",
            "qwen2.5:7b",
            "--json",
        ).output
    )
    assert payload["recommendations"], "nothing survived the hard constraints"
    assert payload["recommendations"][0]["reasons"]


def test_shape_changes_the_ranking_not_just_the_output(invoke):
    """The option exists so two tasks of one type rank differently."""

    def top(*shape: str) -> str:
        args = ["select", "--task", "coding", "--model", "qwen2.5:7b", "--json"]
        if shape:
            args += ["--shape", ",".join(shape)]
        return json.loads(invoke(*args).output)["recommendations"][0]["technique_id"]

    assert top("multi_step", "high_stakes") != top("verifiable", "exact_format")


def test_an_unknown_shape_is_rejected_rather_than_ignored(invoke):
    result = runner.invoke(
        app,
        ["select", "--task", "coding", "--model", "qwen2.5:7b", "--shape", "not_a_shape"],
    )
    assert result.exit_code != 0


def test_max_calls_rules_out_the_expensive_techniques(invoke):
    from prompt_selector.registry import Registry

    payload = json.loads(
        invoke(
            "select",
            "--task",
            "classification",
            "--model",
            "qwen2.5:7b",
            "--max-calls",
            "1",
            "--json",
        ).output
    )
    registry = Registry.load()
    for entry in payload["recommendations"]:
        assert registry.technique(entry["technique_id"]).min_calls <= 1
    assert payload["rejected"], "a budget of one call must reject the multi-call techniques"


def test_select_file_reads_a_saved_profile(invoke):
    assert "Rank" in invoke("select-file", "examples/task_profile.json").output


# --------------------------------------------------------------------------- #
# compilation
# --------------------------------------------------------------------------- #


def test_compile_produces_the_stages_the_technique_declares(invoke):
    from prompt_selector.registry import Registry

    payload = json.loads(
        invoke(
            "compile",
            "--task",
            "structured_extraction",
            "--input-file",
            "examples/book_excerpt.txt",
            "--technique",
            "structured.schema-first",
            "--json",
        ).output
    )
    declared = Registry.load().technique("structured.schema-first").min_calls
    assert len(payload["stages"]) == declared


def test_compile_carries_the_user_input_verbatim(invoke):
    from pathlib import Path

    excerpt = Path("examples/book_excerpt.txt").read_text(encoding="utf-8").strip()
    payload = json.loads(
        invoke(
            "compile",
            "--task",
            "structured_extraction",
            "--input-file",
            "examples/book_excerpt.txt",
            "--technique",
            "structured.schema-first",
            "--json",
        ).output
    )
    rendered = json.dumps(payload)
    assert excerpt.split("\n")[0] in rendered


def test_compile_with_a_schema_reports_how_it_will_be_enforced(invoke):
    payload = json.loads(
        invoke(
            "compile",
            "--task",
            "structured_extraction",
            "--input-file",
            "examples/book_excerpt.txt",
            "--schema-file",
            "examples/entity_schema.json",
            "--technique",
            "structured.schema-first",
            "--capabilities",
            "system_messages",
            "--json",
        ).output
    )
    # Without structured_output the schema goes into the prompt and is validated
    # after the call; the compiler is required to say so rather than imply native
    # enforcement.
    assert payload["notes"]


def test_compile_rejects_a_missing_input_file(invoke):
    result = runner.invoke(
        app,
        ["compile", "--task", "structured_extraction", "--input-file", "no/such/file.txt"],
    )
    assert result.exit_code != 0


# --------------------------------------------------------------------------- #
# scaffolding
# --------------------------------------------------------------------------- #


def test_new_technique_writes_a_file_that_the_linter_accepts(invoke, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    invoke("new-technique", "structured.my-technique")
    written = list(tmp_path.rglob("*.yaml"))
    assert written, "new-technique wrote nothing"
    assert "my-technique" in written[0].read_text(encoding="utf-8")
