"""Turn Hugging Face token-classification datasets into benchmark examples.

NER corpora are labelled per token in BIO form. Our benchmark wants one JSON
document per example, so entity spans are collapsed into lists per field — which
is exactly the shape ``field_f1`` already grades.

The one invariant that must not break: a gold value has to appear **verbatim**
in the input, or the model is penalised for failing to reproduce a paraphrase it
was never shown. That is why detokenization tracks character offsets and slices
entity text out of the finished sentence, rather than re-joining tokens
separately and hoping the two agree.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from prompt_playoff.integrations import require

#: Punctuation that attaches to the preceding token.
_CLOSING = set(".,;:!?)]}%’”") | {"'s", "n't", "'re", "'ve", "'ll", "'d", "'m"}
#: Punctuation that attaches to the following token.
_OPENING = set("([{‘“$#")


@dataclass
class Preset:
    """How one dataset maps onto one response schema."""

    repo_id: str
    config: str | None
    split: str
    #: entity type (as it appears in the tags) -> output field name
    mapping: dict[str, str]
    tokens_column: str = "tokens"
    tags_column: str = "ner_tags"
    licence: str = ""
    citation: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def fields(self) -> list[str]:
        seen: list[str] = []
        for name in self.mapping.values():
            if name not in seen:
                seen.append(name)
        return seen


#: MultiCoNER II is the closest public analogue of entity-extraction-hard: its
#: whole premise is entities that are syntactically ambiguous.
MULTICONER_EN = Preset(
    repo_id="MultiCoNER/multiconer_v2",
    config="English (EN)",
    split="validation",
    mapping={
        "Scientist": "people",
        "Artist": "people",
        "Athlete": "people",
        "Politician": "people",
        "Cleric": "people",
        "SportsManager": "people",
        "OtherPER": "people",
        "HumanSettlement": "places",
        "Facility": "places",
        "OtherLOC": "places",
        "Station": "places",
    },
    licence="CC-BY-4.0",
    citation="Fetahu et al., SemEval-2023 Task 2: MultiCoNER II",
    notes=[
        "Only person and location types are kept; MultiCoNER's creative-work and "
        "corporation classes are dropped, so a sentence whose only entity is a film "
        "title becomes an empty example rather than a wrong one."
    ],
)

#: Few-NERD's coarse labels carry no B-/I- prefix, so adjacent distinct entities
#: of the same type merge. That is the corpus's own limitation, not ours.
FEW_NERD = Preset(
    repo_id="DFKI-SLT/few-nerd",
    config="supervised",
    split="validation",
    mapping={"person": "people", "location": "places", "organization": "organizations"},
    licence="CC-BY-SA-4.0 (share-alike: derived datasets must carry the same licence)",
    citation="Ding et al., Few-NERD: A Few-shot Named Entity Recognition Dataset",
    notes=[
        "Coarse labels are not BIO-prefixed, so two adjacent entities of the same "
        "type collapse into one span."
    ],
)


@dataclass
class QAPreset:
    """A dataset of questions with a single checkable answer.

    Different shape from the NER presets: nothing to decode from tags, but the
    answer has to be pulled out of a worked solution and graded numerically.
    """

    repo_id: str
    config: str | None
    split: str
    question_column: str
    answer_column: str
    #: Answer text after this marker, where the corpus writes out its reasoning.
    answer_marker: str | None = None
    numeric: bool = True
    licence: str = ""
    citation: str = ""
    notes: list[str] = field(default_factory=list)


#: GSM8K is where chain-of-thought was shown to matter. Our datasets are all
#: reading tasks, so nothing here could ever show a reasoning technique working.
GSM8K = QAPreset(
    repo_id="openai/gsm8k",
    config="main",
    split="test",
    question_column="question",
    answer_column="answer",
    answer_marker="####",
    licence="MIT",
    citation="Cobbe et al., Training Verifiers to Solve Math Word Problems (arXiv 2110.14168)",
    notes=[
        "The corpus answer is a worked solution ending in '#### <number>'; only that "
        "number is kept as the gold, and grading is numeric so formatting does not count."
    ],
)

PRESETS: dict[str, Preset] = {"multiconer-en": MULTICONER_EN, "few-nerd": FEW_NERD}


@dataclass
class CodePreset:
    """A dataset of programming tasks graded by running their tests."""

    repo_id: str
    config: str | None
    split: str
    prompt_column: str
    tests_column: str
    setup_column: str | None = None
    licence: str = ""
    citation: str = ""
    notes: list[str] = field(default_factory=list)


#: MBPP is the practical choice over HumanEval: its problems are elementary and
#: mostly avoid dependencies outside the sandbox's small pure-module whitelist.
MBPP = CodePreset(
    repo_id="google-research-datasets/mbpp",
    config="sanitized",
    split="test",
    prompt_column="prompt",
    tests_column="test_list",
    setup_column=None,
    licence="CC-BY-4.0",
    citation="Austin et al., Program Synthesis with Large Language Models (arXiv 2108.07732)",
    notes=[
        "Graded by running the task's own asserts in the restricted interpreter, so the "
        "score is the share of tests that pass, not a text comparison.",
        "Tasks needing modules outside the sandbox's pure math/itertools/collections "
        "whitelist are dropped; scoring them zero would measure the sandbox, not the prompt.",
    ],
)

QA_PRESETS: dict[str, QAPreset] = {"gsm8k": GSM8K}
CODE_PRESETS: dict[str, CodePreset] = {"mbpp": MBPP}


# --------------------------------------------------------------------------- #
# pure conversion — no third-party dependency, so it is testable on its own
# --------------------------------------------------------------------------- #


def detokenize(tokens: list[str]) -> tuple[str, list[tuple[int, int]]]:
    """Join tokens into a sentence and report each token's character span."""
    parts: list[str] = []
    spans: list[tuple[int, int]] = []
    cursor = 0
    attach_next = False
    for index, token in enumerate(tokens):
        space = ""
        if index and not attach_next and token not in _CLOSING and not token.startswith("'"):
            space = " "
        cursor += len(space)
        parts.append(space + token)
        spans.append((cursor, cursor + len(token)))
        cursor += len(token)
        attach_next = token in _OPENING
    return "".join(parts), spans


def decode_spans(tags: list[str]) -> list[tuple[str, int, int]]:
    """Entity spans as (type, first token, last token), inclusive.

    Handles both BIO-prefixed tags and bare type labels; with bare labels a run
    of the same type is one entity, which is all the corpus records.
    """
    spans: list[tuple[str, int, int]] = []
    current: str | None = None
    start = 0
    for index, raw in enumerate(tags):
        tag = raw or "O"
        if tag == "O":
            if current is not None:
                spans.append((current, start, index - 1))
                current = None
            continue
        if "-" in tag and tag.split("-", 1)[0] in {"B", "I", "E", "S"}:
            prefix, kind = tag.split("-", 1)
            begins = prefix in {"B", "S"} or current != kind
        else:
            kind = tag
            begins = current != kind
        if begins:
            if current is not None:
                spans.append((current, start, index - 1))
            current, start = kind, index
        else:
            current = kind
    if current is not None:
        spans.append((current, start, len(tags) - 1))
    return spans


def to_example(
    tokens: list[str],
    tags: list[str],
    preset: Preset,
    example_id: str,
) -> dict[str, Any] | None:
    """One dataset row -> one benchmark example, or None if unusable."""
    if not tokens or len(tokens) != len(tags):
        return None
    text, offsets = detokenize(tokens)
    expected: dict[str, list[str]] = {name: [] for name in preset.fields}
    kinds: set[str] = set()
    for kind, first, last in decode_spans(tags):
        target = preset.mapping.get(kind)
        if target is None:
            continue
        mention = text[offsets[first][0] : offsets[last][1]]
        if mention and mention not in expected[target]:
            expected[target].append(mention)
            kinds.add(kind)
    return {
        "id": example_id,
        "input": text,
        "expected": expected,
        "response_schema": build_schema(preset.fields),
        "tags": sorted({"huggingface", preset.repo_id.split("/")[-1], *kinds}),
    }


def build_schema(fields: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {name: {"type": "array", "items": {"type": "string"}} for name in fields},
        "required": list(fields),
        "additionalProperties": False,
    }


def select(
    examples: list[dict[str, Any]],
    limit: int,
    empty_ratio: float = 0.1,
    seed: int = 20260807,
) -> list[dict[str, Any]]:
    """Sample deterministically, keeping a deliberate slice of empty cases.

    Dropping every empty example would reward a prompt that guesses: precision
    errors need somewhere to show up.
    """
    rng = random.Random(seed)
    empty = [item for item in examples if not any(item["expected"].values())]
    filled = [item for item in examples if any(item["expected"].values())]
    rng.shuffle(empty)
    rng.shuffle(filled)
    empty_target = min(len(empty), int(round(limit * empty_ratio)))
    chosen = filled[: limit - empty_target] + empty[:empty_target]
    rng.shuffle(chosen)
    return chosen[:limit]


# --------------------------------------------------------------------------- #
# the part that needs `datasets`
# --------------------------------------------------------------------------- #


def _encode_url(url: str) -> str:
    """Percent-encode the path so spaces and brackets survive urllib."""
    import urllib.parse

    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit(parts._replace(path=urllib.parse.quote(parts.path)))


def _parquet_urls(repo_id: str, config: str | None, split: str) -> list[str]:
    """Ask the Hub for a config's auto-converted parquet files."""
    import json
    import urllib.parse
    import urllib.request

    path = f"https://huggingface.co/api/datasets/{repo_id}/parquet"
    if config:
        path += "/" + urllib.parse.quote(config) + "/" + urllib.parse.quote(split)
    with urllib.request.urlopen(path, timeout=60) as response:  # noqa: S310 - fixed Hub host
        payload = json.loads(response.read())
    if isinstance(payload, dict):
        payload = payload.get(config or "default", {}).get(split, [])
    return [str(url) for url in payload]


def _rows_from_parquet(
    preset: Preset, max_rows: int | None = None
) -> list[tuple[list[str], list[str]]]:
    """Read the Hub's parquet export directly.

    Handing the https URLs to `datasets` does not work — it resolves them as
    repository paths — so the bytes are fetched and parsed here instead.
    """
    import io
    import urllib.request

    require("pyarrow", "huggingface")
    import pyarrow.parquet as pq

    urls = _parquet_urls(preset.repo_id, preset.config, preset.split)
    if not urls:
        raise RuntimeError(f"No parquet export for {preset.repo_id} {preset.config}/{preset.split}")

    rows: list[tuple[list[str], list[str]]] = []
    for raw_url in urls:
        # Config names contain spaces and brackets ("English (EN)"), which the
        # Hub returns unencoded and urllib refuses.
        url = _encode_url(raw_url)
        with urllib.request.urlopen(url, timeout=300) as response:  # noqa: S310 - fixed Hub host
            table = pq.read_table(io.BytesIO(response.read()))
        columns = table.column_names
        for name in (preset.tokens_column, preset.tags_column):
            if name not in columns:
                raise RuntimeError(f"{preset.repo_id} parquet has no column {name!r}: {columns}")
        for tokens, tags in zip(
            table.column(preset.tokens_column).to_pylist(),
            table.column(preset.tags_column).to_pylist(),
            strict=True,
        ):
            if tags and isinstance(tags[0], int):
                raise RuntimeError(
                    f"{preset.repo_id} parquet stores tags as integers without label names; "
                    "point the preset at a string tag column."
                )
            rows.append((list(tokens or []), [str(tag) for tag in (tags or [])]))
            if max_rows is not None and len(rows) >= max_rows:
                return rows
    return rows


def load_rows(preset: Preset, max_rows: int | None = None) -> list[tuple[list[str], list[str]]]:
    """Fetch (tokens, tags) pairs, resolving ClassLabel integers to names."""
    require("datasets", "huggingface")
    from datasets import load_dataset

    try:
        dataset = load_dataset(preset.repo_id, preset.config, split=preset.split)
    except RuntimeError as exc:
        # Corpora that still ship a loading script cannot be read by datasets>=4,
        # but the Hub's automatic parquet conversion of the same rows can be.
        if "Dataset scripts are no longer supported" not in str(exc):
            raise
        return _rows_from_parquet(preset, max_rows)

    feature = dataset.features[preset.tags_column]
    names = getattr(getattr(feature, "feature", None), "names", None)

    rows: list[tuple[list[str], list[str]]] = []
    for index, row in enumerate(dataset):
        if max_rows is not None and index >= max_rows:
            break
        tags = row[preset.tags_column]
        if names is not None and tags and isinstance(tags[0], int):
            tags = [names[value] for value in tags]
        rows.append((list(row[preset.tokens_column]), [str(tag) for tag in tags]))
    return rows


def qa_example(
    question: str, answer: str, preset: QAPreset, example_id: str
) -> dict[str, Any] | None:
    """One question/answer row -> one benchmark example."""
    question = " ".join((question or "").split())
    raw = answer or ""
    if preset.answer_marker and preset.answer_marker in raw:
        raw = raw.split(preset.answer_marker)[-1]
    gold = raw.strip().replace(",", "").replace("$", "")
    if not question or not gold:
        return None
    if preset.numeric:
        try:
            value = float(gold)
        except ValueError:
            return None
        gold_value: Any = int(value) if value.is_integer() else value
    else:
        gold_value = gold
    return {
        "id": example_id,
        "input": question,
        "expected": gold_value,
        "response_schema": {
            "type": "object",
            "properties": {"answer": {"type": "number"}},
            "required": ["answer"],
            "additionalProperties": False,
        },
        # Numeric grading: the model may write 18 or 18.0 and both are right.
        "graders": ["numeric_close", "json_validity", "json_schema"],
        "grader_options": {"tolerance": 1e-6},
        "tags": ["huggingface", preset.repo_id.split("/")[-1], "arithmetic"],
    }


def convert_qa(
    preset_name: str, limit: int = 200, scan: int | None = 2000
) -> tuple[list[dict[str, Any]], QAPreset]:
    require("datasets", "huggingface")
    from datasets import load_dataset

    preset = QA_PRESETS[preset_name]
    data = load_dataset(preset.repo_id, preset.config, split=preset.split)
    examples: list[dict[str, Any]] = []
    for index, row in enumerate(data, 1):
        if scan is not None and index > scan:
            break
        example = qa_example(
            row[preset.question_column],
            row[preset.answer_column],
            preset,
            f"{preset_name}-{index:04d}",
        )
        if example is not None:
            examples.append(example)
        if len(examples) >= limit:
            break
    return examples, preset


def code_example(row: dict[str, Any], preset: CodePreset, example_id: str) -> dict[str, Any] | None:
    """One programming task -> one benchmark example, or None if unusable here."""
    prompt = " ".join((row.get(preset.prompt_column) or "").split())
    tests = [str(t) for t in (row.get(preset.tests_column) or []) if str(t).strip()]
    setup_parts = [str(row.get(preset.setup_column) or "")] if preset.setup_column else []
    setup_parts.extend(str(item) for item in (row.get("test_imports") or []) if str(item).strip())
    setup = "\n".join(part for part in setup_parts if part.strip())
    if not prompt or not tests:
        return None
    # Keep tasks using the sandbox's pre-bound pure names, but continue dropping
    # every dynamic or non-whitelisted dependency.
    from prompt_playoff.sandbox import imports_are_supported

    reference = str(row.get("code") or "")
    blob = "\n".join([setup, reference, *tests])
    if not imports_are_supported(blob):
        return None

    # Import compatibility alone is insufficient: an otherwise valid task can
    # still rely on an AST feature the restricted interpreter intentionally
    # omits. Keep the benchmark honest by requiring its supplied reference to
    # pass every assertion before exposing the task to a model.
    if reference.strip():
        from prompt_playoff.sandbox import run_program

        for assertion in tests:
            program = "\n".join(part for part in (reference, setup, assertion) if part.strip())
            if not run_program(program).ok:
                return None

    # The first assert shows the expected function name and signature — without it
    # the model cannot know what to call the function, and every test would fail.
    signature = tests[0]
    return {
        "id": example_id,
        "input": f"{prompt}\n\nYour function must satisfy this call:\n{signature}",
        "expected": None,
        "graders": ["unit_tests", "python_syntax"],
        "grader_options": {"tests": tests, "test_setup": setup},
        "tags": ["huggingface", "mbpp", "code"],
    }


def convert_code(
    preset_name: str, limit: int = 100, scan: int | None = 400
) -> tuple[list[dict[str, Any]], CodePreset]:
    require("datasets", "huggingface")
    from datasets import load_dataset

    preset = CODE_PRESETS[preset_name]
    data = load_dataset(preset.repo_id, preset.config, split=preset.split)
    examples: list[dict[str, Any]] = []
    for index, row in enumerate(data, 1):
        if scan is not None and index > scan:
            break
        example = code_example(dict(row), preset, f"{preset_name}-{index:04d}")
        if example is not None:
            examples.append(example)
        if len(examples) >= limit:
            break
    return examples, preset


def convert(
    preset_name: str,
    limit: int = 200,
    empty_ratio: float = 0.1,
    scan: int | None = 4000,
) -> tuple[list[dict[str, Any]], Preset]:
    if preset_name not in PRESETS:
        raise ValueError(f"Unknown preset {preset_name!r}. Known: {', '.join(sorted(PRESETS))}")
    preset = PRESETS[preset_name]
    rows = load_rows(preset, max_rows=scan)
    examples = []
    for index, (tokens, tags) in enumerate(rows, 1):
        example = to_example(tokens, tags, preset, f"{preset_name}-{index:04d}")
        if example is not None:
            examples.append(example)
    return select(examples, limit=limit, empty_ratio=empty_ratio), preset
