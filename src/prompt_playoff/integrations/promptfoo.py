"""Export techniques and datasets as a promptfoo project.

promptfoo is good at something this project deliberately is not: running the
same prompt across many providers, in CI, and failing a build on regression.
Rather than reimplement that, we emit its config — with the *same graders*
wired in as Python assertions, so a promptfoo run and a
``prompt-playoff benchmark`` run report the same numbers.

Written artefacts::

    promptfooconfig.yaml
    prompts/<technique>.json      one messages array per technique, nunjucks-templated
    prompt_playoff_asserts.py    bridge that calls our graders
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from prompt_playoff.compiler import PromptCompiler
from prompt_playoff.domain import ModelProfile, TaskProfile, TechniqueSpec
from prompt_playoff.evals import BenchmarkExample
from prompt_playoff.graders import default_graders

#: Replaced by the nunjucks variable after compilation, so the exported prompt is
#: byte-identical to what we would send, except for the templated hole.
INPUT_SENTINEL = "@@PROMPT_PLAYOFF_INPUT@@"

ASSERT_BRIDGE = '''"""promptfoo assertion bridge — calls the project's own graders.

promptfoo passes each test's vars, so the expected answer, response schema and
grader options travel with the test case and the score here is the same number
`prompt-playoff benchmark` would report.
"""

from prompt_playoff.graders import GradeContext, run_graders


def get_assert(output, context):
    variables = context.get("vars", {}) if isinstance(context, dict) else {}
    names = variables.get("graders") or []
    if not names:
        return {"pass": True, "score": 1.0, "reason": "no graders declared for this case"}

    grades = run_graders(
        list(names),
        GradeContext(
            output=output if isinstance(output, str) else str(output),
            expected=variables.get("expected"),
            response_schema=variables.get("response_schema"),
            options=variables.get("grader_options") or {},
        ),
    )
    if not grades:
        return {"pass": True, "score": 1.0, "reason": "no grader applied to this case"}

    threshold = float(variables.get("threshold", 0.999))
    score = sum(grades.values()) / len(grades)
    return {
        "pass": score >= threshold,
        "score": score,
        "reason": ", ".join(f"{name}={value:.3f}" for name, value in sorted(grades.items())),
    }
'''


@dataclass
class ExportResult:
    config_path: Path
    prompt_paths: list[Path] = field(default_factory=list)
    bridge_path: Path | None = None
    warnings: list[str] = field(default_factory=list)


def provider_id(model: ModelProfile) -> str:
    if model.provider == "ollama":
        return f"ollama:chat:{model.model_id}"
    return f"openai:chat:{model.model_id}"


def provider_entry(
    model: ModelProfile, response_schema: dict[str, Any] | None = None
) -> dict[str, Any]:
    """The exported prompt assumes native schema enforcement, so the provider
    config must actually enable it — otherwise promptfoo would measure a
    different setup than `prompt-playoff benchmark` does."""
    entry: dict[str, Any] = {"id": provider_id(model)}
    config: dict[str, Any] = {"temperature": 0.1}
    if model.base_url:
        config["apiBaseUrl"] = model.base_url
    if response_schema is not None:
        if model.provider == "ollama":
            config["format"] = response_schema
        else:
            config["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "prompt_playoff_response",
                    "strict": True,
                    "schema": response_schema,
                },
            }
    entry["config"] = config
    return entry


def build_prompt_file(
    task: TaskProfile,
    technique: TechniqueSpec,
    example: BenchmarkExample,
    compiler: PromptCompiler | None = None,
) -> tuple[list[dict[str, str]], list[str], Any]:
    """Compile the technique once and swap the input for a nunjucks variable."""
    compiler = compiler or PromptCompiler()
    program = compiler.compile(
        task=task,
        technique=technique,
        user_input=INPUT_SENTINEL,
        response_schema=example.response_schema,
        variables=example.variables,
        exemplars=example.exemplars,
    )
    warnings: list[str] = []
    if program.expected_calls > 1:
        warnings.append(
            f"{technique.id} runs as {program.strategy} with {program.expected_calls} calls; "
            "promptfoo will evaluate only its first stage. Use `prompt-playoff benchmark` "
            "for the full technique."
        )
    stage = program.main
    messages = [
        {"role": message.role, "content": message.content.replace(INPUT_SENTINEL, "{{input}}")}
        for message in stage.messages
    ]
    return messages, warnings, program


def build_config(
    task: TaskProfile,
    techniques: list[TechniqueSpec],
    dataset: list[BenchmarkExample],
    models: list[ModelProfile],
    dataset_name: str,
    prompt_dir: str = "prompts",
    bridge_module: str = "prompt_playoff_asserts.py",
) -> tuple[dict[str, Any], dict[str, list[dict[str, str]]], list[str]]:
    if not dataset:
        raise ValueError("Cannot export an empty dataset")
    if not techniques:
        raise ValueError("Provide at least one technique")

    warnings: list[str] = []
    schemas = {json.dumps(item.response_schema, sort_keys=True) for item in dataset}
    if len(schemas) > 1:
        warnings.append(
            "Examples declare different response schemas. The exported prompt embeds the "
            "first one; promptfoo cannot vary a compiled prompt per example."
        )

    prompts: list[dict[str, str]] = []
    files: dict[str, list[dict[str, str]]] = {}
    native_schema: dict[str, Any] | None = None
    for technique in techniques:
        messages, technique_warnings, program = build_prompt_file(task, technique, dataset[0])
        warnings += technique_warnings
        native_schema = native_schema or program.response_schema
        slug = technique.id.replace(".", "-")
        files[slug] = messages
        prompts.append({"id": f"file://{prompt_dir}/{slug}.json", "label": technique.id})

    tests: list[dict[str, Any]] = []
    for example in dataset:
        graders = example.graders or default_graders(
            example.expected, example.response_schema, task.constraints.strict_json
        )
        graders = list(dict.fromkeys([*graders, *techniques[0].recipe.validators]))
        variables: dict[str, Any] = {"input": example.input, "graders": graders}
        if example.expected is not None:
            variables["expected"] = example.expected
        if example.response_schema is not None:
            variables["response_schema"] = example.response_schema
        if example.grader_options:
            variables["grader_options"] = example.grader_options
        variables.update(example.variables)

        assertions: list[dict[str, Any]] = [
            {"type": "python", "value": f"file://{bridge_module}:get_assert"}
        ]
        if example.response_schema is not None:
            assertions.insert(0, {"type": "is-json", "value": example.response_schema})

        tests.append(
            {
                "description": example.id,
                "vars": variables,
                "assert": assertions,
            }
        )

    config: dict[str, Any] = {
        "description": (
            f"prompt-playoff export: {len(techniques)} technique(s) × {len(models)} "
            f"provider(s) on {dataset_name}"
        ),
        "prompts": prompts,
        "providers": [provider_entry(model, native_schema) for model in models],
        "tests": tests,
    }
    return config, files, warnings


def export(
    directory: Path,
    task: TaskProfile,
    techniques: list[TechniqueSpec],
    dataset: list[BenchmarkExample],
    models: list[ModelProfile],
    dataset_name: str = "inline",
) -> ExportResult:
    config, files, warnings = build_config(
        task=task,
        techniques=techniques,
        dataset=dataset,
        models=models,
        dataset_name=dataset_name,
    )
    directory.mkdir(parents=True, exist_ok=True)
    prompt_dir = directory / "prompts"
    prompt_dir.mkdir(exist_ok=True)

    prompt_paths: list[Path] = []
    for slug, messages in files.items():
        path = prompt_dir / f"{slug}.json"
        path.write_text(json.dumps(messages, indent=2, ensure_ascii=False), encoding="utf-8")
        prompt_paths.append(path)

    bridge_path = directory / "prompt_playoff_asserts.py"
    bridge_path.write_text(ASSERT_BRIDGE, encoding="utf-8")

    config_path = directory / "promptfooconfig.yaml"
    config_path.write_text(
        yaml.safe_dump(config, sort_keys=False, allow_unicode=True, width=120), encoding="utf-8"
    )
    return ExportResult(
        config_path=config_path,
        prompt_paths=prompt_paths,
        bridge_path=bridge_path,
        warnings=warnings,
    )
