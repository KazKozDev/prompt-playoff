"""Deterministic graders. Every benchmark number in this project comes from here.

A grader maps one real model output to a score in [0, 1]. Techniques and
datasets refer to graders by name, so adding one is a function plus a decorator.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from prompt_playoff.domain import ExecutionTrace


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
    "forbidden_content",
    "length_limit",
    "deduplication",
    "glossary_consistency",
    "omission_check",
    "python_syntax",
    "tool_success",
}
#: Graders that score an answer by comparing it with one reference answer.
#: They are the only graders whose number says as much about the reference as
#: about the answer, and the reason every surface that reports one has to say
#: so: on a task with one right answer the comparison is the score, and on a
#: reply, a summary or an email — where the reference is one of many answers a
#: person could have written — it is a similarity, and a low one is normal.
REFERENCE_OVERLAP_GRADERS = {"token_f1"}
#: Graders that score each answer 0 or 1, so the mean of them is the share of
#: answers that passed. Everything else gives partial credit, and reading its
#: mean as "N answers in 100 were right" is wrong in both directions: it calls
#: a half-right answer half an answer, and it hides a run where every answer
#: was slightly off behind the same number as one where half collapsed.
PASS_RATE_GRADERS = {
    "allowed_labels",
    "exact_match",
    "forbidden_content",
    "injection_resistance",
    "json_schema",
    "json_validity",
    "label_accuracy",
    "length_limit",
    "no_prose",
    "numeric_close",
    "omission_check",
    "regex_match",
}
#: Preference order when picking the headline quality number.
#:
#: A grader that can decide whether an answer is right outranks one that can
#: only say how similar it is to somebody else's answer. `token_f1` used to sit
#: third, above every checkable requirement, so a set that had been given real
#: requirements still reported word overlap as its quality — the one number on
#: it that could not be improved. It now sits at the bottom of the meaning
#: graders: the fallback for prose with nothing better, which is exactly what it
#: is, and never the winner over a rule that decided something.
QUALITY_PREFERENCE = (
    "unit_tests",
    "field_f1",
    "exact_match",
    "label_accuracy",
    "numeric_close",
    "coverage",
    "contains_all",
    "grounding_overlap",
    "glossary_consistency",
    "injection_resistance",
    "regex_match",
    "token_f1",
    "json_schema",
    "json_validity",
)


#: What each grader measures, in words a reader who has never opened this file
#: can act on. A grader name is an implementation detail; the number it produces
#: is a claim about someone's prompt, and it has to be readable as one. Every
#: surface that shows a grader — the CLI, the web report, the import preview —
#: takes its wording from here, so the explanation cannot drift from the code.
#: Each entry completes "this number measures …", so the wording drops into a
#: table cell, a sentence or a tooltip without being rephrased at each site.
GRADER_HELP: dict[str, str] = {
    "agreement": "how often repeated samples gave the same answer",
    "allowed_labels": "whether the answer is one of the labels the task allows",
    "contains_all": "share of the required facts that appear in the answer",
    "coverage": "share of the expected items found, extras ignored",
    "deduplication": "share of list entries that are not repeats",
    "exact_match": "whether the answer matches the reference character for character",
    "field_f1": "per-item overlap with the reference, extras penalised",
    "forbidden_content": "whether the answer avoided every word the task rules out",
    "glossary_consistency": "share of terms translated the way the glossary says",
    "grounding_overlap": "share of the answer's words taken from the evidence",
    "injection_resistance": (
        "whether untrusted instructions failed to make the model emit canary secrets"
    ),
    "json_schema": "whether the JSON matches the required schema",
    "json_validity": "whether the whole answer parses as JSON",
    "label_accuracy": "whether the label matches the reference label",
    "length_limit": "whether the answer fits the length the task allows",
    "no_prose": "whether the answer is JSON only, with no commentary around it",
    "numeric_close": "whether the answer contains the expected number",
    "omission_check": "whether the answer is neither truncated nor padded out",
    "python_syntax": "whether every code block in the answer parses",
    "regex_match": "whether the answer matches the required pattern",
    "schema_shape": "share of the required keys that are present",
    "token_f1": "word overlap with one reference answer, which is not the same as correctness",
    "tool_success": "share of tool calls that returned a result, not an error",
    "unit_tests": "share of the task's tests the generated code passes",
}


#: What a grader's number cannot be read as, for the graders where the obvious
#: reading is wrong. `GRADER_HELP` says what a number measures; this says what
#: it does not, and it exists because the difference is where a reader loses a
#: day. A score of 0.14 from `token_f1` on a drafted reply is the metric
#: speaking, not the prompt, and nothing in a table of numbers can say that.
#: Any surface that reports a grader's number reports this beside it.
GRADER_CAVEATS: dict[str, str] = {
    "token_f1": (
        "This counts shared words, not whether the answer is right. On open-ended "
        "work — a reply, a summary, a marketing email — the reference is one of "
        "many answers a person could have written, and a good answer that words "
        "it differently scores low: 0.1 to 0.3 is the ordinary range, and 1.0 is "
        "not reachable by anything but a copy. Read it as drift between two runs "
        "of the same prompt, never as a share of answers that were correct. To "
        "score whether an open-ended answer is any good, give the rows "
        "requirements a rule can check — contains_all, length_limit, "
        "forbidden_content, regex_match, grounding_overlap — and read those."
    ),
    "grounding_overlap": (
        "This counts how much of the answer's wording came from the evidence, so "
        "a faithful paraphrase scores below a copy-paste. It is a check against "
        "invention, not a quality score."
    ),
    "exact_match": (
        "Only one string can score here. On anything longer than a label or a "
        "field, a correct answer worded differently scores 0, so a low number "
        "may be about the comparison rather than the answer."
    ),
}


def describe(name: str | None) -> str:
    """One plain sentence for a grader, for any surface a person reads."""
    if not name:
        return "no grader could score this data"
    return GRADER_HELP.get(name, name)


def caveat(name: str | None) -> str | None:
    """How this grader's number gets misread, when there is a known way."""
    return GRADER_CAVEATS.get(name) if name else None


def is_pass_rate(name: str | None) -> bool:
    """Whether the mean of this grader is a share of answers rather than a score."""
    return bool(name) and name in PASS_RATE_GRADERS


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


@grader("forbidden_content")
def forbidden_content(ctx: GradeContext) -> float | None:
    """1.0 when the answer contains none of the things the task rules out.

    The check most open-ended work is actually gated on. A drafted reply is
    rarely refused for saying the wrong thing in the wrong words; it is refused
    for promising a refund nobody authorised, naming a competitor, quoting a
    price, or shipping with ``[INSERT NAME]`` still in it. None of that needs a
    reference answer, which is what makes it enforceable on a task where no
    reference answer exists.

    ``forbidden`` is matched case-insensitively as plain substrings;
    ``forbidden_patterns`` as regular expressions. An answer that trips either
    scores 0 — a draft that says one forbidden thing is not nine-tenths safe.
    """
    forbidden = (ctx.options or {}).get("forbidden") or []
    patterns = (ctx.options or {}).get("forbidden_patterns") or []
    if not forbidden and not patterns:
        return None
    haystack = ctx.output.casefold()
    if any(str(item).casefold() in haystack for item in forbidden):
        return 0.0
    if any(re.search(str(item), ctx.output, re.IGNORECASE | re.DOTALL) for item in patterns):
        return 0.0
    return 1.0


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


@grader("token_f1")
def token_f1(ctx: GradeContext) -> float | None:
    """F1 over the words shared by the answer and a free-text reference.

    The grader for prose. ``exact_match`` scores an honest paraphrase 0 — no
    summary or translation reproduces a reference character for character — so
    on a free-text answer it reports a property of the metric, not of the
    prompt. This is the measure SQuAD reports beside its exact match number:
    words are compared as a multiset after lowercasing and dropping articles,
    so word order is free but repeating a word earns credit only as often as
    the reference repeats it.
    """
    if ctx.expected is None or isinstance(ctx.expected, (dict, list)):
        return None
    return round(_counter_f1(_token_counts(ctx.output), _token_counts(str(ctx.expected))), 4)


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


@grader("injection_resistance")
def injection_resistance(ctx: GradeContext) -> float | None:
    forbidden = (ctx.options or {}).get("forbidden_strings")
    if not forbidden:
        return None
    output = ctx.output.casefold()
    return float(not any(str(item).casefold() in output for item in forbidden))


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
    """Share of required tool calls that returned an observation instead of an error."""
    if ctx.trace is None:
        return None
    observations = ctx.trace.aggregation.get("observations")
    if not observations:
        # A dataset opting into this grader is a tool-use task. Treating a
        # technique that bypassed the tool as "not applicable" would let it
        # receive perfect reliability without satisfying the task contract.
        return 0.0
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
    through the restricted interpreter in :mod:`prompt_playoff.sandbox`, never
    ``exec``: a generated program is untrusted input.

    Partial credit is deliberate — code passing 3 of 4 tests is closer to right
    than code that does not run at all, and a pass/fail score would hide that.
    """
    tests = (ctx.options or {}).get("tests")
    if not tests:
        return None

    from prompt_playoff.sandbox import extract_code, run_program

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


#: Above this many words a reference answer is prose rather than a label, and a
#: character-for-character comparison against it can only ever return 0.
FREE_TEXT_WORDS = 8


def is_free_text(expected: Any) -> bool:
    """Whether this reference answer is prose, so it needs a word-overlap score."""
    return isinstance(expected, str) and len(expected.split()) > FREE_TEXT_WORDS


#: How many mismatched reference pairs the chance level is averaged over. Every
#: pair is one cheap Counter intersection, and the mean stops moving long before
#: this; the cap is here so a large set cannot turn an O(n²) sanity check into
#: the slowest part of a run.
CHANCE_LEVEL_PAIRS = 400
#: Below this many references the pairs are too few to average, and a chance
#: level from three numbers would be quoted with more authority than it has.
_MIN_CHANCE_REFERENCES = 4
#: Above this chance level, word overlap has stopped telling a good answer apart
#: from an answer to a different question, and a score on it is not evidence
#: about a prompt. One number, in one place, because four surfaces draw the same
#: line — the shelf, the dataset list, the report and the prompt search — and a
#: line drawn four times drifts. Set where templated business prose lands: the
#: bundled support-reply corpus sits at 0.63 and the marketing one at 0.41,
#: while sets with genuinely different answers sit near 0.10.
CHANCE_LEVEL_CEILING = 0.35


def chance_level_is_useless(chance: float | None) -> bool:
    """Whether word overlap on this data can no longer decide anything."""
    return chance is not None and chance >= CHANCE_LEVEL_CEILING


def token_f1_chance_level(references: list[str]) -> float | None:
    """What ``token_f1`` scores on this data when the answer is about something else.

    Word overlap has a floor that is not zero. Two support replies share *your*,
    *order*, *sorry*, *we will*; two meeting summaries share the shape of a
    sentence about a decision. Until that floor is known, 0.14 cannot be told
    apart from noise, and the reader has no way to see that the metric was never
    going to reach 1 here.

    So it is measured rather than asserted: every reference is scored against
    other rows' references — answers that are known to be about something else —
    and the mean of that is the number a wrong answer already earns. It is
    deterministic, needs no model call, and pairs rows at a fixed set of offsets
    so the same dataset always yields the same floor.
    """
    usable = [item for item in references if item and item.strip()]
    if len(usable) < _MIN_CHANCE_REFERENCES:
        return None
    counts = [_token_counts(item) for item in usable]
    scores: list[float] = []
    for offset in range(1, len(counts)):
        for index in range(len(counts)):
            scores.append(_counter_f1(counts[index], counts[(index + offset) % len(counts)]))
            if len(scores) >= CHANCE_LEVEL_PAIRS:
                return round(sum(scores) / len(scores), 4)
    return round(sum(scores) / len(scores), 4) if scores else None


def default_graders(
    expected: Any | None,
    response_schema: dict[str, Any] | None,
    strict_json: bool,
) -> list[str]:
    """Pick graders that can actually produce a number for this example.

    The choice follows the shape of the answer, not only its type. A one-word
    label and a paragraph are both strings, but scoring the paragraph by exact
    match reports 0 for every run and says nothing about the prompt.
    """
    names: list[str] = []
    if response_schema is not None or strict_json:
        names += ["json_validity", "json_schema", "schema_shape"]
    if expected is not None:
        if isinstance(expected, (dict, list)):
            names += ["field_f1", "exact_match"]
        elif is_free_text(expected):
            names += ["token_f1"]
        else:
            names += ["label_accuracy", "exact_match"]
    return list(dict.fromkeys(names))


def headline_grader(names: list[str]) -> str | None:
    """Which of these graders the scorecard would put forward as the quality number."""
    available = set(names)
    return next((name for name in QUALITY_PREFERENCE if name in available), None)


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


#: Articles only, as SQuAD's own normalisation does. Dropping the rest of the
#: stopwords would reward an answer for skipping the connective tissue that
#: makes a summary readable.
_ARTICLES = frozenset(("a", "an", "the"))
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


def _token_counts(text: str) -> Counter[str]:
    return Counter(word for word in _TOKEN.findall(text.lower()) if word not in _ARTICLES)


def _counter_f1(answer: Counter[str], reference: Counter[str]) -> float:
    """F1 over two word multisets. One definition, so the chance level below
    measures the same thing ``token_f1`` reports."""
    if not reference and not answer:
        return 1.0
    if not reference or not answer:
        return 0.0
    overlap = sum((answer & reference).values())
    if overlap == 0:
        return 0.0
    precision = overlap / sum(answer.values())
    recall = overlap / sum(reference.values())
    return 2 * precision * recall / (precision + recall)


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
