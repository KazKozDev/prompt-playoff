from prompt_selector.compiler import PromptCompiler
from prompt_selector.domain import Capability, Constraints, ModelProfile, TaskProfile, TaskType
from prompt_selector.normalizer import normalize_description


def user_text(program, stage: int = 0) -> str:
    return program.stages[stage].messages[1].content


def test_native_schema_is_passed_to_the_provider(extraction_task, entity_schema, registry) -> None:
    program = PromptCompiler().compile(
        extraction_task, registry.technique("structured.schema-first"), "Input", entity_schema
    )
    assert program.response_schema == entity_schema
    assert "json_schema" in program.validators
    assert program.expected_calls == 1


def test_schema_is_embedded_when_the_model_cannot_enforce_it(entity_schema, registry) -> None:
    task = TaskProfile(
        task_type=TaskType.structured_extraction,
        constraints=Constraints(strict_json=True),
        model=ModelProfile(capabilities={Capability.system_messages}),
    )
    program = PromptCompiler().compile(
        task, registry.technique("structured.schema-first"), "Input", entity_schema
    )
    assert program.response_schema is None
    assert '"required"' in user_text(program)
    assert any("no native structured output" in note for note in program.notes)


def test_each_technique_produces_its_own_prompt_shape(extraction_task, entity_schema, registry):
    schema_first = PromptCompiler().compile(
        extraction_task,
        registry.technique("structured.schema-first"),
        "Mara went to Veyr.",
        entity_schema,
    )
    few_shot = PromptCompiler().compile(
        extraction_task,
        registry.technique("structured.few-shot-repair"),
        "Mara went to Veyr.",
        entity_schema,
    )
    assert user_text(schema_first) != user_text(few_shot)
    assert "PROCEDURE" in user_text(schema_first)
    assert "RULES" in user_text(few_shot)


def test_multi_stage_technique_compiles_one_prompt_per_stage(
    extraction_task, entity_schema, registry
):
    program = PromptCompiler().compile(
        extraction_task, registry.technique("structured.few-shot-repair"), "Input", entity_schema
    )
    assert program.strategy == "multi_stage"
    assert [stage.stage for stage in program.stages] == ["draft", "repair"]
    assert program.expected_calls == 2
    # The repair stage waits on the draft, so its slot stays open until execution.
    assert "previous" in program.stages[1].deferred_placeholders


def test_self_consistency_declares_the_calls_it_will_make(extraction_task, entity_schema, registry):
    program = PromptCompiler().compile(
        extraction_task, registry.technique("reasoning.self-consistency"), "Input", entity_schema
    )
    assert program.strategy == "self_consistency"
    assert program.expected_calls == 3
    assert program.strategy_params["samples"] == 3


def test_exemplars_come_from_the_request_not_the_technique(
    extraction_task, entity_schema, registry
):
    from prompt_selector.domain import Exemplar

    without = PromptCompiler().compile(
        extraction_task, registry.technique("structured.few-shot-repair"), "Input", entity_schema
    )
    assert any("demonstrations" in note for note in without.notes)

    with_demos = PromptCompiler().compile(
        extraction_task,
        registry.technique("structured.few-shot-repair"),
        "Input",
        entity_schema,
        exemplars=[
            Exemplar(
                input="Ada met Bo in Rome.", output='{"people":["Ada","Bo"],"places":["Rome"]}'
            )
        ],
    )
    assert "Ada met Bo in Rome." in user_text(with_demos)


def test_every_technique_compiles_and_includes_the_input(registry, extraction_task, entity_schema):
    for technique in registry.techniques.values():
        task = extraction_task.model_copy(deep=True)
        task.task_type = next(iter(technique.strong_tasks), TaskType.summarization)
        task.constraints.tools_allowed = technique.tools_required
        task.constraints.max_calls = max(technique.min_calls, 3)
        program = PromptCompiler().compile(task, technique, "MARKER-INPUT", entity_schema)
        assert program.stages, technique.id
        rendered = " ".join(user_text(program, i) for i in range(len(program.stages)))
        assert "{input}" not in rendered, technique.id
        if technique.execution.strategy != "map_reduce":
            assert "MARKER-INPUT" in rendered, technique.id


def test_tools_are_attached_only_when_allowed(extraction_task, registry):
    task = extraction_task.model_copy(deep=True)
    task.task_type = TaskType.agents
    task.constraints.tools_allowed = True
    program = PromptCompiler().compile(task, registry.technique("agents.react"), "Compute 6*7")
    assert program.stages[0].tools
    assert any(tool["function"]["name"] == "calculator" for tool in program.stages[0].tools)

    task.constraints.tools_allowed = False
    program = PromptCompiler().compile(task, registry.technique("agents.react"), "Compute 6*7")
    assert program.stages[0].tools == []


def test_legacy_recipe_without_blocks_still_compiles(extraction_task, registry):
    technique = registry.technique("structured.schema-first").model_copy(deep=True)
    technique.recipe.blocks = []
    program = PromptCompiler().compile(extraction_task, technique, "Legacy input")
    assert "Legacy input" in user_text(program)
    assert "INSTRUCTIONS" in user_text(program)


def test_retrieval_task_without_tools_is_flagged_in_the_notes(registry) -> None:
    description = "собери в интернете статьи про архитектуры агентов ллм за 2026 год"
    task = normalize_description(
        description, ModelProfile(capabilities={Capability.system_messages})
    )
    program = PromptCompiler().compile(
        task, registry.technique("reasoning.decomposition"), description
    )

    assert task.constraints.retrieval_required is True
    assert any("declares no tools" in note for note in program.notes)


def test_a_recipe_can_word_itself_for_a_request_that_supplies_nothing(registry) -> None:
    technique = registry.technique("reasoning.self-ask")
    topic = TaskProfile(
        task_type=TaskType.research,
        constraints=Constraints(supplied_material=False, requires_validation=False),
        model=ModelProfile(capabilities={Capability.system_messages}),
    )
    supplied = topic.model_copy(
        update={"constraints": Constraints(supplied_material=True, requires_validation=False)}
    )

    for_topic = user_text(PromptCompiler().compile(topic, technique, "рынок ИИ в ЕС"))
    for_material = user_text(PromptCompiler().compile(supplied, technique, "a long report"))

    assert "from what you reliably know" in for_topic
    assert "using only the input" not in for_topic
    assert "using only the input" in for_material
