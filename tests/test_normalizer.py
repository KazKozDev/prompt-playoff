from prompt_selector.compiler import PromptCompiler
from prompt_selector.domain import Capability, ModelProfile, TaskShape, TaskType
from prompt_selector.normalizer import normalize_description


def test_normalizer_infers_extraction_and_json() -> None:
    model = ModelProfile(capabilities={Capability.structured_output, Capability.system_messages})
    result = normalize_description(
        "Extract entities into strict JSON. Reliability matters most.", model
    )
    assert result.task_type == TaskType.structured_extraction
    assert result.constraints.strict_json is True
    assert result.priorities.reliability == 0.5


def test_normalizer_recognizes_russian_python_assignment_as_coding(registry) -> None:
    description = "напиши игру змейка в питоне"
    model = ModelProfile(capabilities={Capability.system_messages})

    task = normalize_description(description, model)
    program = PromptCompiler().compile(
        task,
        registry.technique("direct.explicit-constraints"),
        description,
    )
    user_message = program.stages[0].messages[1].content

    assert task.task_type == TaskType.coding
    assert task.constraints.requires_validation is True
    assert "Perform this coding task" in user_message
    assert "summarization" not in user_message
    assert description in user_message


def test_normalizer_does_not_treat_every_game_mention_as_coding() -> None:
    model = ModelProfile(capabilities={Capability.system_messages})

    task = normalize_description("Кратко опиши правила игры в шахматы", model)

    assert task.task_type == TaskType.summarization


def test_normalizer_preserves_extraction_precedence_over_russian_python_cue() -> None:
    model = ModelProfile(capabilities={Capability.system_messages})

    task = normalize_description("Извлеки код на Питоне в JSON", model)

    assert task.task_type == TaskType.structured_extraction


def test_normalizer_marks_web_collection_as_retrieval_required() -> None:
    model = ModelProfile(capabilities={Capability.system_messages})

    task = normalize_description(
        "собери в интернете все статьи про архитектуры агентов ллм за 2026 год", model
    )

    assert task.constraints.retrieval_required is True
    assert task.constraints.tools_allowed is True


def test_normalizer_leaves_supplied_material_as_not_retrieval() -> None:
    model = ModelProfile(capabilities={Capability.system_messages})

    task = normalize_description(
        "Ответь на вопрос, опираясь только на приложенные источники ниже", model
    )

    assert task.constraints.retrieval_required is False


def test_normalizer_reads_the_shape_of_a_stepped_request() -> None:
    model = ModelProfile(capabilities={Capability.system_messages})

    task = normalize_description(
        "спроектируй сервис очередей: сначала схема данных, затем API, потом деплой", model
    )

    assert TaskShape.multi_step in task.shape


def test_normalizer_calls_a_bare_request_underspecified() -> None:
    model = ModelProfile(capabilities={Capability.system_messages})

    assert TaskShape.underspecified in normalize_description("почини баг", model).shape


def test_normalizer_does_not_call_a_short_clear_request_underspecified() -> None:
    model = ModelProfile(capabilities={Capability.system_messages})

    task = normalize_description("классифицируй тикеты поддержки по категориям", model)

    assert TaskShape.underspecified not in task.shape
    assert TaskShape.verifiable in task.shape


def test_two_requests_of_one_type_get_different_shapes() -> None:
    model = ModelProfile(capabilities={Capability.system_messages})

    quick = normalize_description("напиши функцию сортировки списка", model)
    designed = normalize_description(
        "спроектируй систему платежей: сначала схема, затем API, потом миграция", model
    )

    assert quick.task_type is designed.task_type
    assert quick.shape != designed.shape
