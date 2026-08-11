"""Adding a technique must be a YAML file and nothing else."""

import textwrap

import pytest
import yaml

from prompt_selector.compiler import PromptCompiler
from prompt_selector.graders import grader_names
from prompt_selector.lint import has_errors, lint_registry, lint_technique
from prompt_selector.registry import Registry, RegistryError
from prompt_selector.strategies import strategy_names

NEW_TECHNIQUE = textwrap.dedent(
    """
    id: custom.bullet-summary
    version: 1.0.0
    title: Bullet summary
    family: custom
    description: Summarize into a fixed number of bullets.
    strong_tasks: [summarization]
    acceptable_tasks: []
    avoid_tasks: [coding]
    required_capabilities: [system_messages]
    model_classes: [small, medium, large, reasoning]
    min_calls: 1
    tools_required: false
    strict_json_fit: false
    validation_fit: true
    characteristics:
      quality: 0.75
      reliability: 0.8
      latency_efficiency: 0.9
      token_efficiency: 0.9
      simplicity: 0.95
    recipe:
      system: Summarize without adding facts.
      instructions: [Keep every bullet to one clause.]
      variables:
        bullet_count: "5"
      blocks:
        - name: role
          title: OBJECTIVE
          body: "Summarize the input into exactly {bullet_count} bullets.\\n"
        - name: rules
          title: RULES
          body: "{instructions}\\n"
        - name: input
          title: INPUT
          body: "{input}\\n"
      validators: [contains_all]
      fallback: Retry with a stricter bullet limit.
    execution:
      strategy: single
    benchmark_priors:
      default: 0.7
    evidence_level: heuristic
    tags: []
    """
)


def write_registry(tmp_path, extra_yaml: str | None = None):
    """Copy the shipped registry into a temp dir so a new file can be dropped in."""
    source = Registry.load()
    root = tmp_path / "data"
    (root / "techniques").mkdir(parents=True)
    (root / "models").mkdir(parents=True)
    (root / "datasets").mkdir(parents=True)
    for technique in source.techniques.values():
        payload = technique.model_dump(mode="json")
        (root / "techniques" / f"{technique.id.replace('.', '-')}.yaml").write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )
    for (provider, model_id), profile in source.models.items():
        (root / "models" / f"{provider}-{model_id}.yaml".replace(":", "-")).write_text(
            yaml.safe_dump(profile.model_dump(mode="json"), sort_keys=False), encoding="utf-8"
        )
    if extra_yaml:
        (root / "techniques" / "zz-new.yaml").write_text(extra_yaml, encoding="utf-8")
    return root


def test_a_new_technique_needs_only_a_yaml_file(tmp_path, extraction_task):
    root = write_registry(tmp_path, NEW_TECHNIQUE)
    registry = Registry.load(root)

    assert "custom.bullet-summary" in registry.techniques
    assert not has_errors(lint_registry(registry))

    technique = registry.technique("custom.bullet-summary")
    program = PromptCompiler().compile(extraction_task, technique, "Some long text.")
    body = program.stages[0].messages[1].content
    assert "exactly 5 bullets" in body  # recipe variable resolved
    assert "Some long text." in body
    assert program.strategy == "single"


def test_a_request_variable_overrides_the_recipe_default(tmp_path, extraction_task):
    registry = Registry.load(write_registry(tmp_path, NEW_TECHNIQUE))
    program = PromptCompiler().compile(
        extraction_task,
        registry.technique("custom.bullet-summary"),
        "Some long text.",
        variables={"bullet_count": "3"},
    )
    assert "exactly 3 bullets" in program.stages[0].messages[1].content


def test_a_typo_in_a_placeholder_is_caught_by_lint(tmp_path):
    broken = NEW_TECHNIQUE.replace("{bullet_count}", "{bullet_kount}")
    registry = Registry.load(write_registry(tmp_path, broken))
    issues = lint_technique(registry.technique("custom.bullet-summary"))
    assert has_errors(issues)
    assert any("bullet_kount" in issue.message for issue in issues)


def test_an_unknown_strategy_is_caught_by_lint(tmp_path):
    broken = NEW_TECHNIQUE.replace("strategy: single", "strategy: telepathy")
    registry = Registry.load(write_registry(tmp_path, broken))
    issues = lint_technique(registry.technique("custom.bullet-summary"))
    assert has_errors(issues)
    assert any("telepathy" in issue.message for issue in issues)


def test_bad_strategy_params_are_caught_by_lint(tmp_path):
    broken = NEW_TECHNIQUE.replace(
        "  strategy: single", "  strategy: self_consistency\n  params:\n    samples: 99"
    )
    registry = Registry.load(write_registry(tmp_path, broken))
    assert has_errors(lint_technique(registry.technique("custom.bullet-summary")))


def test_a_stage_referencing_a_missing_block_fails_to_load(tmp_path):
    broken = NEW_TECHNIQUE.replace(
        "  strategy: single",
        "  strategy: multi_stage\n  stages:\n    - name: one\n      blocks: [ghost]",
    )
    with pytest.raises(RegistryError, match="unknown blocks"):
        Registry.load(write_registry(tmp_path, broken))


def test_the_shipped_registry_is_clean():
    assert lint_registry(Registry.load()) == [] or not has_errors(lint_registry(Registry.load()))


def test_every_shipped_validator_maps_to_a_real_grader():
    known = set(grader_names())
    for technique in Registry.load().techniques.values():
        assert set(technique.recipe.validators) <= known, technique.id


def test_every_shipped_strategy_is_registered():
    for technique in Registry.load().techniques.values():
        assert technique.execution.strategy in strategy_names(), technique.id


def test_an_evidence_claim_without_a_source_is_an_error(registry):
    """`documented` with nothing behind it is exactly what this rule exists to stop."""
    from prompt_selector.domain import EvidenceLevel
    from prompt_selector.lint import has_errors, lint_technique

    technique = registry.technique("reasoning.step-back").model_copy(deep=True)
    assert technique.source is not None  # shipped with one

    technique.source = None
    issues = lint_technique(technique)
    assert has_errors(issues)
    assert any("no source is given" in issue.message for issue in issues)

    # Dropping the claim instead of naming the paper is the other valid fix.
    technique.evidence_level = EvidenceLevel.heuristic
    assert not has_errors(lint_technique(technique))


def test_every_shipped_evidence_claim_is_backed(registry):
    from prompt_selector.domain import EvidenceLevel

    for technique in registry.techniques.values():
        if technique.evidence_level is not EvidenceLevel.heuristic:
            assert technique.source is not None, technique.id
            assert technique.source.paper, technique.id
            assert technique.source.url, technique.id


def test_sources_point_at_a_resolvable_identifier(registry):
    """A citation that cannot be looked up is decoration."""
    for technique in registry.techniques.values():
        if technique.source and technique.source.url:
            assert technique.source.url.startswith("https://arxiv.org/abs/"), technique.id
            assert technique.source.year, technique.id


TWO_STAGE = NEW_TECHNIQUE.replace(
    "execution:\n  strategy: single\n",
    "execution:\n"
    "  strategy: multi_stage\n"
    "  stages:\n"
    "    - name: first\n"
    "      blocks: [role, input]\n"
    "    - name: second\n"
    "      blocks: [rules, input]\n",
).replace("min_calls: 1", "min_calls: 2")


def test_a_second_call_that_reads_nothing_from_the_first_is_an_error(tmp_path):
    """Two stages that never chain are one prompt, and the extra call is unpaid for."""
    registry = Registry.load(write_registry(tmp_path, TWO_STAGE))

    issues = lint_technique(registry.technique("custom.bullet-summary"))

    assert has_errors(issues)
    assert any("reads nothing from the stage before" in issue.message for issue in issues)


def test_a_second_call_that_consumes_the_first_is_accepted(tmp_path):
    chained = (
        TWO_STAGE.replace(
            '      body: "{instructions}\\n"',
            '      body: "{instructions}\\nEarlier: {previous}\\n"',
        )
        .replace("latency_efficiency: 0.9", "latency_efficiency: 0.5")
        .replace("token_efficiency: 0.9", "token_efficiency: 0.5")
    )
    registry = Registry.load(write_registry(tmp_path, chained))

    assert not has_errors(lint_technique(registry.technique("custom.bullet-summary")))


def test_claiming_thrift_while_spending_a_second_call_is_flagged(tmp_path):
    chained = TWO_STAGE.replace(
        '      body: "{instructions}\\n"',
        '      body: "{instructions}\\nEarlier: {previous}\\n"',
    )
    registry = Registry.load(write_registry(tmp_path, chained))

    issues = lint_technique(registry.technique("custom.bullet-summary"))

    assert not has_errors(issues)
    assert any("spends exactly what the recipe claims to save" in issue.message for issue in issues)


def test_the_shipped_registry_spends_no_unearned_calls() -> None:
    """The two-stage mould put a second call on five recipes that never needed one."""
    issues = lint_registry(Registry.load())

    assert not has_errors(issues)
    assert not [issue for issue in issues if "claims to save" in issue.message]
