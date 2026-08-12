"""Registry checks that make adding a technique safe.

Everything a YAML file can get wrong — a typo'd placeholder, an unknown
strategy, a grader that does not exist, a stage referencing a missing block —
is caught here rather than at the first real model call.
"""

from __future__ import annotations

from dataclasses import dataclass

from prompt_playoff.domain import (
    Capability,
    Constraints,
    EvidenceLevel,
    ModelProfile,
    TaskProfile,
    TechniqueSpec,
)
from prompt_playoff.graders import grader_names
from prompt_playoff.registry import Registry
from prompt_playoff.strategies import get_strategy, strategy_names
from prompt_playoff.templating import known_placeholders, placeholders_in


@dataclass
class LintIssue:
    technique_id: str
    level: str  # "error" | "warning"
    message: str

    def __str__(self) -> str:
        return f"[{self.level}] {self.technique_id}: {self.message}"


def lint_registry(registry: Registry) -> list[LintIssue]:
    issues: list[LintIssue] = []
    for technique in registry.techniques.values():
        issues += lint_technique(technique)
    return issues


def lint_technique(technique: TechniqueSpec) -> list[LintIssue]:
    issues: list[LintIssue] = []
    error = lambda message: issues.append(LintIssue(technique.id, "error", message))  # noqa: E731
    warn = lambda message: issues.append(LintIssue(technique.id, "warning", message))  # noqa: E731

    # 1. Strategy exists and its params validate.
    try:
        strategy = get_strategy(technique.execution.strategy)
    except Exception as exc:
        error(str(exc))
        return issues
    params = None
    try:
        params = strategy.parse_params(technique.execution.params)
    except Exception as exc:
        error(f"invalid execution.params: {exc}")

    declared_stages = {stage.name for stage in technique.execution.stages}
    for required in strategy.required_stages:
        if required not in declared_stages:
            error(f"strategy {strategy.name!r} requires a stage named {required!r}")

    # 2. Placeholders resolve.
    allowed = known_placeholders(technique)
    sources = [("system", technique.recipe.system)]
    sources += [(f"block:{block.name}", block.body) for block in technique.recipe.blocks]
    sources += [
        (f"stage:{stage.name}.system", stage.system)
        for stage in technique.execution.stages
        if stage.system
    ]
    for label, text in sources:
        unknown = placeholders_in(text) - allowed
        if unknown:
            error(f"{label} uses unknown placeholders: {', '.join(sorted(unknown))}")

    # 3. Validators map to real graders.
    known_graders = set(grader_names())
    for name in technique.recipe.validators:
        if name not in known_graders:
            warn(
                f"validator {name!r} has no grader, so it cannot be measured "
                f"(known: {', '.join(sorted(known_graders))})"
            )

    # 4. Declared call count matches what the strategy will actually do.
    if params is not None:
        stage_count = len(technique.execution.stages) or 1
        expected = strategy.expected_calls(params, stage_count)
        if technique.min_calls > expected:
            warn(f"min_calls={technique.min_calls} but {strategy.name} issues {expected} call(s)")

    # 5. The recipe must actually render.
    if not technique.recipe.blocks:
        warn("no prompt blocks declared; falling back to the generic legacy layout")
    issues += _render_probe(technique)

    # 6. An evidence claim above "heuristic" has to name what backs it.
    if technique.evidence_level is not EvidenceLevel.heuristic and technique.source is None:
        error(
            f"evidence_level is {technique.evidence_level.value!r} but no source is given — "
            "either name the publication or drop to 'heuristic'"
        )
    if technique.source is not None and technique.evidence_level is EvidenceLevel.heuristic:
        warn("a source is given but evidence_level is still 'heuristic'")

    # 7. Consistency checks that used to be silent.
    overlap = technique.strong_tasks & technique.avoid_tasks
    if overlap:
        error(
            f"tasks listed as both strong and avoid: {', '.join(sorted(t.value for t in overlap))}"
        )
    if technique.strict_json_fit and not technique.recipe.validators:
        warn("declares strict_json_fit but lists no validators")

    # 8. `suits` is what makes selection about the request rather than its task
    # type. A recipe that claims nothing never wins on shape; one that claims
    # everything wins every request, which is the same as claiming nothing.
    if not technique.suits:
        warn("declares no `suits`: it can never win on what a request looks like")
    elif len(technique.suits) > 4:
        error(
            f"declares {len(technique.suits)} shapes in `suits`; keep it to four, "
            "so the claim still separates this recipe from the others"
        )

    # 9. An extra model call has to be earned. Several recipes were written from a
    # two-stage mould and spent a second call on a method the paper runs in one
    # prompt, which doubles the user's cost and re-sends the whole input.
    issues.extend(_extra_call_issues(technique))
    return issues


def _extra_call_issues(technique: TechniqueSpec) -> list[LintIssue]:
    """Check that a second call does work a second call is needed for."""
    issues: list[LintIssue] = []
    bodies = {block.name: block.body for block in technique.recipe.blocks}
    if technique.execution.strategy == "multi_stage":
        for stage in technique.execution.stages[1:]:
            used: set[str] = set()
            for name in stage.blocks:
                used |= placeholders_in(bodies.get(name, ""))
            if "previous" not in used:
                issues.append(
                    LintIssue(
                        technique.id,
                        "error",
                        f"stage {stage.name!r} is a separate model call but reads nothing from "
                        "the stage before it ({previous}); make it a block of the previous "
                        "stage instead of a second call",
                    )
                )
    characteristics = technique.characteristics
    claims_thrift = (
        characteristics.token_efficiency >= 0.7
        or characteristics.latency_efficiency >= 0.7
        or "token-efficient" in technique.tags
    )
    if technique.min_calls >= 2 and claims_thrift:
        issues.append(
            LintIssue(
                technique.id,
                "warning",
                f"declares {technique.min_calls} calls while claiming to be cheap or fast "
                "(token_efficiency "
                f"{characteristics.token_efficiency:.2f}, latency_efficiency "
                f"{characteristics.latency_efficiency:.2f}) — an extra round trip spends "
                "exactly what the recipe claims to save",
            )
        )
    return issues


def _render_probe(technique: TechniqueSpec) -> list[LintIssue]:
    """Compile the technique against a synthetic task to prove the recipe renders."""
    from prompt_playoff.compiler import PromptCompiler

    issues: list[LintIssue] = []
    task_type = next(iter(technique.strong_tasks), None) or next(
        iter(technique.acceptable_tasks), None
    )
    if task_type is None:
        return issues

    model = ModelProfile(
        model_class=next(iter(technique.model_classes), ModelProfile().model_class),
        capabilities={Capability.system_messages, *technique.required_capabilities}
        | {Capability.structured_output},
    )
    task = TaskProfile(
        task_type=task_type,
        constraints=Constraints(
            strict_json=technique.strict_json_fit,
            tools_allowed=technique.tools_required,
            max_calls=max(technique.min_calls, 3),
        ),
        model=model,
    )
    schema = {
        "type": "object",
        "properties": {"result": {"type": "string"}},
        "required": ["result"],
    }
    try:
        program = PromptCompiler().compile(task, technique, "probe input", schema)
    except Exception as exc:
        issues.append(LintIssue(technique.id, "error", f"failed to compile: {exc}"))
        return issues

    for stage in program.stages:
        if not stage.messages[1].content.strip():
            issues.append(
                LintIssue(
                    technique.id, "error", f"stage {stage.stage!r} renders an empty user message"
                )
            )
        if "{input}" in stage.messages[1].content:
            issues.append(
                LintIssue(technique.id, "error", f"stage {stage.stage!r} left {{input}} unrendered")
            )
    if program.strategy == "single" and "probe input" not in program.main.messages[1].content:
        issues.append(
            LintIssue(
                technique.id, "warning", "the task input does not appear in the compiled prompt"
            )
        )
    return issues


def format_issues(issues: list[LintIssue]) -> str:
    if not issues:
        return "No issues."
    return "\n".join(str(issue) for issue in issues)


def has_errors(issues: list[LintIssue]) -> bool:
    return any(issue.level == "error" for issue in issues)


def registry_summary(registry: Registry) -> dict[str, object]:
    return {
        "techniques": len(registry.techniques),
        "models": len(registry.models),
        "datasets": sorted(registry.datasets),
        "strategies": strategy_names(),
        "graders": grader_names(),
    }
