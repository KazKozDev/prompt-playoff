"""Deterministic graders. Every benchmark number in this project comes from here.

A grader maps one real model output to a score in [0, 1]. Techniques and
datasets refer to graders by name, so adding one is a function plus a decorator.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from prompt_selector.domain import ExecutionTrace


@dataclass
class GradeContext:
    output: str
    expected: Any | None = None
    response_schema: dict[str, Any] | None = None
    trace: ExecutionTrace | None = None
    options: dict[str, Any] | None = None

    @property
    def parsed(self) -> Any | None:
        return parse_json(self.output)


Grader = Callable[[GradeContext], float | None]

_GRADERS: dict[str, Grader] = {}
#: Graders that measure contract compliance rather than answer quality.
RELIABILITY_GRADERS = {
    "json_validity",
    "json_schema",
    "no_prose",
    "allowed_labels",
    "length_limit",
    "deduplication",
    "glossary_consistency",
    "omission_check",
    "python_syntax",
    "tool_success",
}
#: Preference order when picking the headline quality number.
QUALITY_PREFERENCE = (
    "unit_tests",
    "field_f1",
    "exact_match",
    "label_accuracy",
    "numeric_close",
    "coverage",
    "grounding_overlap",
    "contains_all",
    "regex_match",
    "json_schema",
    "json_validity",
)


GraderT = TypeVar("GraderT", bound=Grader)


def grader(name: str) -> Callable[[GraderT], GraderT]:
    def wrapper(func: GraderT) -> GraderT:
        _GRADERS[name] = func
        return func

    return wrapper


def get_grader(name: str) -> Grader:
    try:
        return _GRADERS[name]
    except KeyError as exc:
        known = ", ".join(sorted(_GRADERS))
        raise KeyError(f"Unknown grader {name!r}. Known: {known}") from exc


def grader_names() -> list[str]:
    return sorted(_GRADERS)


def parse_json(text: str) -> Any | None:
    stripped = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", stripped, re.DOTALL)
    if fence:
        stripped = fence.group(1)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    # Tolerate a single JSON object embedded in prose; contract graders still fail it.
    match = re.search(r"[\{\[].*[\}\]]", stripped, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None


# --------------------------------------------------------------------------- #
# contract graders
# --------------------------------------------------------------------------- #


@grader("json_validity")
def json_validity(ctx: GradeContext) -> float:
    stripped = ctx.output.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", stripped, re.DOTALL)
    if fence:
        stripped = fence.group(1)
    try:
        json.loads(stripped)
    except json.JSONDecodeError:
        return 0.0
    return 1.0


@grader("no_prose")
def no_prose(ctx: GradeContext) -> float:
    """1.0 only when the whole response is the JSON document, with no commentary."""
    return json_validity(ctx)


@grader("json_schema")
def json_schema(ctx: GradeContext) -> float | None:
    if ctx.response_schema is None:
        return None
    errors = validate_schema(ctx.parsed, ctx.response_schema)
    return 1.0 if not errors else 0.0


@grader("schema_shape")
def schema_shape(ctx: GradeContext) -> float | None:
    """Partial credit: the fraction of required top-level keys that are present."""
    if ctx.response_schema is None:
        return None
    parsed = ctx.parsed
    if not isinstance(parsed, dict):
        return 0.0
    required = ctx.response_schema.get("required") or []
    if not required:
        return 1.0
    return sum(1 for key in required if key in parsed) / len(required)


@grader("length_limit")
def length_limit(ctx: GradeContext) -> float | None:
    limit = (ctx.options or {}).get("max_chars")
    if not limit:
        return None
    return 1.0 if len(ctx.output.strip()) <= int(limit) else 0.0


@grader("allowed_labels")
def allowed_labels(ctx: GradeContext) -> float | None:
    allowed = (ctx.options or {}).get("labels")
    if not allowed:
        return None
    produced = _label_of(ctx)
    return 1.0 if produced in {str(item).strip().lower() for item in allowed} else 0.0


# --------------------------------------------------------------------------- #
# quality graders
# --------------------------------------------------------------------------- #


@grader("exact_match")
def exact_match(ctx: GradeContext) -> float | None:
    if ctx.expected is None:
        return None
    if isinstance(ctx.expected, (dict, list)):
        parsed = ctx.parsed
        if parsed is None:
            return 0.0
        return float(_canonical(parsed) == _canonical(ctx.expected))
    return float(ctx.output.strip() == str(ctx.expected).strip())


@grader("field_f1")
def field_f1(ctx: GradeContext) -> float | None:
    """Micro F1 over the items of an expected object-of-lists or list.

    This is the grader that makes extraction quality a real number instead of a
    pass/fail: getting 3 of 4 entities right scores 0.86, not 0.
    """
    if ctx.expected is None:
        return None
    parsed = ctx.parsed
    if parsed is None:
        return 0.0

    expected_items = _collect_items(ctx.expected)
    actual_items = _collect_items(parsed)
    if expected_items is None or actual_items is None:
        return None
    if not expected_items and not actual_items:
        return 1.0

    true_positive = len(expected_items & actual_items)
    precision = true_positive / len(actual_items) if actual_items else 0.0
    recall = true_positive / len(expected_items) if expected_items else 0.0
    if precision + recall == 0:
        return 0.0
    return round(2 * precision * recall / (precision + recall), 4)


@grader("label_accuracy")
def label_accuracy(ctx: GradeContext) -> float | None:
    if ctx.expected is None or isinstance(ctx.expected, (dict, list)):
        return None
    return float(_label_of(ctx) == str(ctx.expected).strip().lower())


@grader("contains_all")
def contains_all(ctx: GradeContext) -> float | None:
    needles = (ctx.options or {}).get("contains")
    if not needles:
        return None
    haystack = ctx.output.lower()
    hits = sum(1 for needle in needles if str(needle).lower() in haystack)
    return hits / len(needles)


@grader("regex_match")
def regex_match(ctx: GradeContext) -> float | None:
    pattern = (ctx.options or {}).get("pattern")
    if not pattern:
        return None
    return 1.0 if re.search(str(pattern), ctx.output, re.DOTALL) else 0.0


@grader("numeric_close")
def numeric_close(ctx: GradeContext) -> float | None:
    if ctx.expected is None:
        return None
    try:
        target = float(ctx.expected)
    except (TypeError, ValueError):
        return None
    numbers = re.findall(r"-?\d+(?:\.\d+)?", ctx.output)
    if not numbers:
        return 0.0
    tolerance = float((ctx.options or {}).get("tolerance", 1e-6))
    return 1.0 if any(abs(float(item) - target) <= tolerance for item in numbers) else 0.0


@grader("coverage")
def coverage(ctx: GradeContext) -> float | None:
    """Recall only: the share of expected items the output found, ignoring extras."""
    if ctx.expected is None:
        return None
    parsed = ctx.parsed
    if parsed is None:
        return 0.0
    expected_items = _collect_items(ctx.expected)
    actual_items = _collect_items(parsed)
    if expected_items is None or actual_items is None:
        return None
    if not expected_items:
        return 1.0
    return round(len(expected_items & actual_items) / len(expected_items), 4)


@grader("deduplication")
def deduplication(ctx: GradeContext) -> float | None:
    """1.0 when no list in the output repeats a value."""
    parsed = ctx.parsed
    if parsed is None:
        return None
    duplicates, total = _count_duplicates(parsed)
    if total == 0:
        return None
    return round(1.0 - duplicates / total, 4)


@grader("glossary_consistency")
def glossary_consistency(ctx: GradeContext) -> float | None:
    """Share of required glossary renderings that appear in the output."""
    glossary = (ctx.options or {}).get("glossary")
    if not glossary:
        return None
    targets = list(glossary.values()) if isinstance(glossary, dict) else list(glossary)
    if not targets:
        return None
    haystack = ctx.output.lower()
    hits = sum(1 for term in targets if str(term).lower() in haystack)
    return round(hits / len(targets), 4)


@grader("omission_check")
def omission_check(ctx: GradeContext) -> float | None:
    """Flags truncated output by comparing length against the source."""
    source = (ctx.options or {}).get("source")
    if not source:
        return None
    ratio = len(ctx.output.strip()) / max(len(str(source).strip()), 1)
    low = float((ctx.options or {}).get("min_ratio", 0.5))
    high = float((ctx.options or {}).get("max_ratio", 2.0))
    return 1.0 if low <= ratio <= high else 0.0


@grader("grounding_overlap")
def grounding_overlap(ctx: GradeContext) -> float | None:
    """Share of content words in the answer that also occur in the supplied evidence."""
    evidence = (ctx.options or {}).get("evidence")
    if not evidence:
        return None
    evidence_words = _content_words(str(evidence))
    answer_words = _content_words(ctx.output)
    if not answer_words:
        return 0.0
    grounded = sum(1 for word in answer_words if word in evidence_words)
    return round(grounded / len(answer_words), 4)


@grader("tool_success")
def tool_success(ctx: GradeContext) -> float | None:
    """Share of tool calls that returned an observation instead of an error."""
    if ctx.trace is None:
        return None
    observations = ctx.trace.aggregation.get("observations")
    if not observations:
        return None
    failures = sum(
        1 for item in observations if str(item.get("observation", "")).startswith("error:")
    )
    return round(1.0 - failures / len(observations), 4)


@grader("python_syntax")
def python_syntax(ctx: GradeContext) -> float | None:
    """1.0 when every fenced Python block in the answer parses."""
    blocks = re.findall(r"```(?:python|py)?\s*(.*?)```", ctx.output, re.DOTALL)
    if not blocks:
        return None
    import ast

    ok = 0
    for block in blocks:
        try:
            ast.parse(block)
            ok += 1
        except SyntaxError:
            pass
    return round(ok / len(blocks), 4)


@grader("unit_tests")
def unit_tests(ctx: GradeContext) -> float | None:
    """Run the model's code against the task's tests and report the share that pass.

    This is the only grader here that executes what the model wrote. It goes
    through the restricted interpreter in :mod:`prompt_selector.sandbox`, never
    ``exec``: a generated program is untrusted input.

    Partial credit is deliberate — code passing 3 of 4 tests is closer to right
    than code that does not run at all, and a pass/fail score would hide that.
    """
    tests = (ctx.options or {}).get("tests")
    if not tests:
        return None

    from prompt_selector.sandbox import extract_code, run_program

    code = extract_code(ctx.output)
    if not code.strip():
        return 0.0
    setup = (ctx.options or {}).get("test_setup") or ""

    passed = 0
    for assertion in tests:
        program = "\n".join(part for part in (code, setup, str(assertion)) if part.strip())
        if run_program(program).ok:
            passed += 1
    return round(passed / len(tests), 4)


@grader("agreement")
def agreement(ctx: GradeContext) -> float | None:
    """Measured sample agreement, available only for multi-sample strategies."""
    if ctx.trace is None:
        return None
    value = ctx.trace.aggregation.get("agreement")
    return float(value) if value is not None else None


# --------------------------------------------------------------------------- #
# selection + a compact JSON Schema validator
# --------------------------------------------------------------------------- #


def default_graders(
    expected: Any | None,
    response_schema: dict[str, Any] | None,
    strict_json: bool,
) -> list[str]:
    """Pick graders that can actually produce a number for this example."""
    names: list[str] = []
    if response_schema is not None or strict_json:
        names += ["json_validity", "json_schema", "schema_shape"]
    if expected is not None:
        if isinstance(expected, (dict, list)):
            names += ["field_f1", "exact_match"]
        else:
            names += ["label_accuracy", "exact_match"]
    return list(dict.fromkeys(names))


def run_graders(names: list[str], ctx: GradeContext) -> dict[str, float]:
    grades: dict[str, float] = {}
    for name in names:
        try:
            score = get_grader(name)(ctx)
        except KeyError:
            continue
        if score is not None:
            grades[name] = round(float(score), 4)
    return grades


def validate_schema(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    """A compact, dependency-free JSON Schema check covering what recipes emit."""
    errors: list[str] = []
    if value is None and schema.get("type") != "null":
        return [f"{path}: missing value"]

    expected_type = schema.get("type")
    if expected_type and not _type_ok(value, expected_type):
        return [f"{path}: expected {expected_type}, got {_type_name(value)}"]

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} is not one of {schema['enum']}")

    if expected_type == "object" or isinstance(value, dict):
        properties = schema.get("properties") or {}
        for key in schema.get("required") or []:
            if not isinstance(value, dict) or key not in value:
                errors.append(f"{path}.{key}: required key missing")
        if isinstance(value, dict):
            if schema.get("additionalProperties") is False:
                for key in value:
                    if key not in properties:
                        errors.append(f"{path}.{key}: additional property not allowed")
            for key, subschema in properties.items():
                if key in value:
                    errors += validate_schema(value[key], subschema, f"{path}.{key}")

    if expected_type == "array" or isinstance(value, list):
        items = schema.get("items")
        if isinstance(items, dict) and isinstance(value, list):
            for index, item in enumerate(value):
                errors += validate_schema(item, items, f"{path}[{index}]")
        if isinstance(value, list):
            minimum, maximum = schema.get("minItems"), schema.get("maxItems")
            if minimum is not None and len(value) < minimum:
                errors.append(f"{path}: expected at least {minimum} items")
            if maximum is not None and len(value) > maximum:
                errors.append(f"{path}: expected at most {maximum} items")
    return errors


def _type_ok(value: Any, expected: str | list[str]) -> bool:
    if isinstance(expected, list):
        return any(_type_ok(value, item) for item in expected)
    mapping = {
        "object": dict,
        "array": list,
        "string": str,
        "number": (int, float),
        "integer": int,
        "boolean": bool,
        "null": type(None),
    }
    python_type = mapping.get(expected)
    if python_type is None:
        return True
    if expected in {"number", "integer"} and isinstance(value, bool):
        return False
    return isinstance(value, python_type)


def _type_name(value: Any) -> str:
    for name, checker in (
        ("null", lambda v: v is None),
        ("boolean", lambda v: isinstance(v, bool)),
        ("array", lambda v: isinstance(v, list)),
        ("object", lambda v: isinstance(v, dict)),
        ("string", lambda v: isinstance(v, str)),
        ("number", lambda v: isinstance(v, (int, float))),
    ):
        if checker(value):
            return name
    return type(value).__name__


def _canonical(value: Any) -> str:
    return json.dumps(_sorted(value), sort_keys=True, ensure_ascii=False)


def _sorted(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _sorted(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return sorted(
            (_sorted(item) for item in value),
            key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=False),
        )
    return value


def _collect_items(value: Any) -> set[str] | None:
    """Flatten an expected/actual answer into comparable ``field::item`` tokens."""
    if isinstance(value, list):
        return {f"::{_norm(item)}" for item in value}
    if isinstance(value, dict):
        items: set[str] = set()
        for key, entry in value.items():
            if isinstance(entry, list):
                items |= {f"{key}::{_norm(item)}" for item in entry}
            else:
                items.add(f"{key}::{_norm(entry)}")
        return items
    return None


def _norm(value: Any) -> str:
    if isinstance(value, str):
        return " ".join(value.lower().split())
    return json.dumps(_sorted(value), sort_keys=True, ensure_ascii=False)


_STOPWORDS = frozenset(
    "a an the of to in on for and or but is are was were be been it its this that with as at by "
    "from not no if then than so such which who whom what when where how".split()
)


def _content_words(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Zа-яА-ЯёЁ0-9']{3,}", text.lower())
    return {word for word in words if word not in _STOPWORDS}


def _count_duplicates(value: Any) -> tuple[int, int]:
    """(duplicate entries, total entries) across every list in the document."""
    duplicates = total = 0
    if isinstance(value, list):
        keys = [_norm(item) for item in value]
        total += len(keys)
        duplicates += len(keys) - len(set(keys))
        for item in value:
            sub_duplicates, sub_total = _count_duplicates(item)
            duplicates += sub_duplicates
            total += sub_total
    elif isinstance(value, dict):
        for item in value.values():
            sub_duplicates, sub_total = _count_duplicates(item)
            duplicates += sub_duplicates
            total += sub_total
    return duplicates, total


def _label_of(ctx: GradeContext) -> str:
    parsed = ctx.parsed
    if isinstance(parsed, dict):
        for key in ("label", "class", "category", "answer"):
            if key in parsed and isinstance(parsed[key], str):
                return parsed[key].strip().lower()
    if isinstance(parsed, str):
        return parsed.strip().lower()
    return ctx.output.strip().lower()
