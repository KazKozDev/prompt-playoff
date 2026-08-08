from prompt_selector.domain import ExecutionTrace
from prompt_selector.graders import (
    GradeContext,
    default_graders,
    grader_names,
    run_graders,
    validate_schema,
)


def ctx(output, **kwargs):
    return GradeContext(output=output, **kwargs)


def test_json_validity_rejects_prose_around_json():
    assert run_graders(["json_validity"], ctx('{"a":1}'))["json_validity"] == 1.0
    assert run_graders(["json_validity"], ctx('Here you go: {"a":1}'))["json_validity"] == 0.0


def test_json_validity_accepts_a_fenced_block():
    assert run_graders(["json_validity"], ctx('```json\n{"a":1}\n```'))["json_validity"] == 1.0


def test_field_f1_gives_partial_credit(entity_schema):
    expected = {"people": ["Mara", "Orin"], "places": ["Veyr"]}
    perfect = ctx('{"people":["Mara","Orin"],"places":["Veyr"]}', expected=expected)
    partial = ctx('{"people":["Mara"],"places":["Veyr"]}', expected=expected)
    wrong = ctx('{"people":["Zed"],"places":["Nowhere"]}', expected=expected)

    assert run_graders(["field_f1"], perfect)["field_f1"] == 1.0
    assert 0.5 < run_graders(["field_f1"], partial)["field_f1"] < 1.0
    assert run_graders(["field_f1"], wrong)["field_f1"] == 0.0


def test_field_f1_is_case_and_order_insensitive():
    expected = {"people": ["Mara", "Orin"]}
    scrambled = ctx('{"people":["orin","MARA"]}', expected=expected)
    assert run_graders(["field_f1"], scrambled)["field_f1"] == 1.0


def test_coverage_ignores_extra_items_but_f1_does_not():
    expected = {"people": ["Mara"]}
    noisy = ctx('{"people":["Mara","Extra","More"]}', expected=expected)
    grades = run_graders(["coverage", "field_f1"], noisy)
    assert grades["coverage"] == 1.0
    assert grades["field_f1"] < 1.0


def test_schema_validation_catches_wrong_types_and_extra_keys(entity_schema):
    assert validate_schema({"people": [], "places": []}, entity_schema) == []
    assert validate_schema({"people": "Mara", "places": []}, entity_schema)
    assert validate_schema({"people": [], "places": [], "extra": 1}, entity_schema)
    assert validate_schema({"people": []}, entity_schema)
    assert validate_schema({"people": [1], "places": []}, entity_schema)


def test_json_schema_grader_is_all_or_nothing_but_shape_is_partial(entity_schema):
    partial = ctx('{"people":[]}', response_schema=entity_schema)
    grades = run_graders(["json_schema", "schema_shape"], partial)
    assert grades["json_schema"] == 0.0
    assert grades["schema_shape"] == 0.5


def test_deduplication_penalises_repeats():
    assert run_graders(["deduplication"], ctx('{"a":["x","y"]}'))["deduplication"] == 1.0
    assert run_graders(["deduplication"], ctx('{"a":["x","x"]}'))["deduplication"] == 0.5


def test_grounding_overlap_measures_evidence_reuse():
    options = {"evidence": "The satellite carries an infrared camera."}
    grounded = run_graders(["grounding_overlap"], ctx("infrared camera", options=options))
    invented = run_graders(
        ["grounding_overlap"], ctx("nuclear submarine periscope", options=options)
    )
    assert grounded["grounding_overlap"] > invented["grounding_overlap"]


def test_tool_success_reads_the_execution_trace():
    ok = ExecutionTrace(
        technique_id="t",
        strategy="tool_loop",
        output="",
        aggregation={
            "observations": [{"observation": '{"result": 1}'}, {"observation": "error: boom"}]
        },
    )
    assert run_graders(["tool_success"], ctx("", trace=ok))["tool_success"] == 0.5


def test_tool_success_rejects_a_tool_task_with_no_tool_call():
    skipped = ExecutionTrace(technique_id="t", strategy="single", output="42")

    assert run_graders(["tool_success"], ctx("42", trace=skipped))["tool_success"] == 0.0


def test_python_syntax_only_scores_fenced_code():
    assert "python_syntax" not in run_graders(["python_syntax"], ctx("no code here"))
    good = run_graders(["python_syntax"], ctx("```python\nx = 1\n```"))
    bad = run_graders(["python_syntax"], ctx("```python\ndef (\n```"))
    assert good["python_syntax"] == 1.0
    assert bad["python_syntax"] == 0.0


def test_graders_that_cannot_apply_return_nothing():
    grades = run_graders(["exact_match", "contains_all", "regex_match", "agreement"], ctx("hello"))
    assert grades == {}


def test_default_graders_follow_the_data(entity_schema):
    assert default_graders(None, entity_schema, True) == [
        "json_validity",
        "json_schema",
        "schema_shape",
    ]
    assert "field_f1" in default_graders({"a": []}, None, False)
    assert "label_accuracy" in default_graders("billing", None, False)


def test_unknown_grader_names_are_skipped_not_fatal():
    assert run_graders(["nope"], ctx('{"a":1}')) == {}
    assert "field_f1" in grader_names()


# --------------------------------------------------------------------------- #
# the sandbox that runs model-written programs
# --------------------------------------------------------------------------- #


def test_sandbox_computes():
    from prompt_selector.sandbox import run_program

    assert run_program("answer = sum([x * x for x in [1, 2, 3]])").value == 14
    assert (
        run_program(
            "```python\ntotal = 0\nfor i in range(4):\n    total += i\nanswer = total\n```"
        ).value
        == 6
    )
    assert run_program("answer = sorted([3, 1, 2])[-1]").value == 3


def test_sandbox_refuses_every_way_out():
    """A model-written program is untrusted input; none of these may run."""
    from prompt_selector.sandbox import run_program

    escapes = [
        "import os\nanswer = os.listdir('/')",
        "answer = ().__class__.__bases__",
        "answer = open('/etc/passwd').read()",
        "answer = eval('1+1')",
        "answer = __import__('os')",
        "answer = [].__len__()",
    ]
    for source in escapes:
        result = run_program(source)
        assert not result.ok, source
        assert result.value is None


def test_sandbox_allows_local_pure_functions():
    """Function definitions are required by MBPP and are not an escape vector."""
    from prompt_selector.sandbox import run_program

    result = run_program("def f():\n    return 1\nanswer = f()")
    assert result.ok
    assert result.value == 1


def test_sandbox_prebinds_only_whitelisted_pure_module_names():
    """Safe imports are declarations; no module object enters the interpreter."""
    from prompt_selector.sandbox import run_program

    programs = {
        "import math\nanswer = math.floor(math.pi)": 3,
        "from math import sqrt as root\nanswer = root(81)": 9.0,
        "from collections import Counter\nanswer = Counter('abaca')": {
            "a": 3,
            "b": 1,
            "c": 1,
        },
        (
            "from collections import defaultdict\n"
            "counts = defaultdict(int)\ncounts['x'] += 1\nanswer = counts['x']"
        ): 1,
        (
            "from itertools import combinations_with_replacement\n"
            "answer = list(combinations_with_replacement('ab', 2))"
        ): [("a", "a"), ("a", "b"), ("b", "b")],
    }
    for source, expected in programs.items():
        result = run_program(source)
        assert result.ok, result.error
        assert result.value == expected


def test_sandbox_rejects_modules_and_members_outside_the_whitelist():
    from prompt_selector.sandbox import run_program

    rejected = [
        "import os\nanswer = 1",
        "from math import __dict__\nanswer = 1",
        "import math\nanswer = math.__class__",
        "import collections\nanswer = collections.ChainMap({}, {})",
        "from itertools import count\nanswer = list(count())",
        "from itertools import product\nanswer = list(product('a', repeat=1001))",
    ]
    for source in rejected:
        result = run_program(source)
        assert not result.ok, source
        assert result.value is None


def test_sandbox_stops_a_runaway_program():
    from prompt_selector.sandbox import run_program

    result = run_program("i = 0\nwhile True:\n    i += 1\nanswer = i")
    assert not result.ok
    assert "steps" in result.error


def test_sandbox_reports_ordinary_errors_as_results():
    """A division by zero is an outcome to tell the model about, not a crash."""
    from prompt_selector.sandbox import run_program

    result = run_program("answer = 1 / 0")
    assert not result.ok
    assert "ZeroDivisionError" in result.error


def test_comprehension_variables_do_not_leak():
    from prompt_selector.sandbox import run_program

    assert run_program("x = 99\nys = [x for x in [1, 2]]\nanswer = x").value == 99
