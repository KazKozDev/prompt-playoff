#!/usr/bin/env python3
"""Download the business catalogue's rows into bundled JSONL sets.

The catalogue in data/business_cases.yaml names, for each business case, a
public dataset in the same input -> output shape. This script turns the `sets`
block of that file into the rows the server measures against, written to
data/datasets/business/<slug>.jsonl.

They are bundled rather than fetched at click time because the point of the
catalogue is that a first run works: a new install can measure a prompt against
the support desk or the invoice reader without a network, an account, or a
column-mapping decision made under a spinner.

Rows come from the Hugging Face datasets server, which serves rows over HTTP
without downloading the whole repository — a few hundred KB per set instead of
gigabytes.

    python scripts/fetch_business_datasets.py            # every set
    python scripts/fetch_business_datasets.py support    # names matching "support"
    python scripts/fetch_business_datasets.py --check    # report, write nothing
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / "src/prompt_playoff/data/business_cases.yaml"
OUT_DIR = ROOT / "src/prompt_playoff/data/datasets/business"
ROWS_API = "https://datasets-server.huggingface.co/rows"
PAGE = 100
# The sample we keep is drawn from a wider window than it needs, because rows
# are dropped for being too long or for having no answer, and a set that asks
# for 60 and gets 12 is not the set the catalogue describes.
WINDOW = 8


class FetchError(RuntimeError):
    pass


# --------------------------------------------------------------------------- #
# the network
# --------------------------------------------------------------------------- #


def fetch_page(spec: dict[str, Any], offset: int) -> list[dict[str, Any]]:
    params = {
        "dataset": spec["source"],
        "config": spec.get("config", "default"),
        "split": spec["split"],
        "offset": offset,
        "length": PAGE,
    }
    url = f"{ROWS_API}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": "prompt-playoff/catalogue"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return [item["row"] for item in json.load(response)["rows"]]
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:200]
            if exc.code in (429, 500, 502, 503) and attempt < 2:
                time.sleep(3 * (attempt + 1))
                continue
            raise FetchError(f"{spec['source']}: HTTP {exc.code} {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt < 2:
                time.sleep(3 * (attempt + 1))
                continue
            raise FetchError(f"{spec['source']}: {exc}") from exc
    return []


# --------------------------------------------------------------------------- #
# row -> (input, expected)
#
# One function per `fetch:` value in the catalogue. Each returns None for a row
# it cannot use, and dropping such a row is always right: an example whose input
# is empty, or whose answer is missing, measures the dataset and not the prompt.
# --------------------------------------------------------------------------- #


def shape_column(row: dict[str, Any], spec: dict[str, Any]) -> tuple[str, Any] | None:
    """The ordinary case: one column in, one column out."""
    text = text_of(row.get(spec["input"]))
    expected = row.get(spec["expected"])
    if not text or expected is None or expected == "":
        return None
    return text, expected


def shape_chat_reply(row: dict[str, Any], spec: dict[str, Any]) -> tuple[str, Any] | None:
    """A chat-shaped thread: the last turn addressed to the writer, and the reply."""
    turns = row.get("prompt") or []
    if isinstance(turns, str):
        return None
    incoming = [turn.get("content", "") for turn in turns if turn.get("role") != "assistant"]
    text = "\n\n".join(part for part in incoming if part).strip()
    reply = text_of(row.get("completion"))
    if not text or not reply:
        return None
    return text, reply


def shape_subject_body(row: dict[str, Any], spec: dict[str, Any]) -> tuple[str, Any] | None:
    """A marketing email stored whole: its subject line in, its body out."""
    whole = text_of(row.get("0"))
    if not whole.startswith("Subject:"):
        return None
    head, _, body = whole.partition("\n")
    body = body.strip()
    if not body:
        return None
    return head.strip(), body


def shape_translation(row: dict[str, Any], spec: dict[str, Any]) -> tuple[str, Any] | None:
    """OPUS-100 keeps both languages in one column."""
    pair = row.get("translation") or {}
    source = text_of(pair.get(spec["translation_from"]))
    target = text_of(pair.get(spec["translation_to"]))
    if not source or not target:
        return None
    return source, target


def shape_nli(row: dict[str, Any], spec: dict[str, Any]) -> tuple[str, Any] | None:
    """A clause and a claim about it; the label named rather than numbered."""
    premise = text_of(row.get("premise"))
    hypothesis = text_of(row.get("hypothesis"))
    labels = spec["labels"]
    index = row.get("label")
    if not premise or not hypothesis or not isinstance(index, int) or index >= len(labels):
        return None
    return f"CLAUSE: {premise}\n\nCLAIM: {hypothesis}", labels[index]


def shape_finqa(row: dict[str, Any], spec: dict[str, Any]) -> tuple[str, Any] | None:
    """A filing is three columns — the prose before the table, the table, the prose after."""
    question = text_of(row.get("question"))
    answer = row.get("answer")
    if not question or answer in (None, ""):
        return None
    parts = [
        " ".join(row.get("pre_text") or []),
        table_text(row.get("table")),
        " ".join(row.get("post_text") or []),
    ]
    report = "\n".join(part for part in parts if part).strip()
    if not report:
        return None
    return f"REPORT:\n{report}\n\nQUESTION: {question}", answer


def shape_invoice_ocr(row: dict[str, Any], spec: dict[str, Any]) -> tuple[str, Any] | None:
    """The OCR words off the scan in, the fields the scan carries out.

    Both columns arrive as JSON inside a string, and the answer is double
    encoded — a JSON string holding JSON. Parsed here rather than left for the
    grader, so the expected value is an object and field_f1 can compare fields.
    """
    raw = json_of(row.get("raw_data")) or {}
    parsed = json_of(row.get("parsed_data")) or {}
    words = text_of(raw.get("ocr_words"))
    fields = parsed.get("json")
    if isinstance(fields, str):
        fields = json_of(fields)
    if not words or not isinstance(fields, dict) or not fields:
        return None
    return words, fields


def shape_instruction_input(row: dict[str, Any], spec: dict[str, Any]) -> tuple[str, Any] | None:
    """An instruction and the facts it applies to, kept as one input."""
    instruction = text_of(row.get("instruction"))
    facts = text_of(row.get("input"))
    output = text_of(row.get("output"))
    if not instruction or not output:
        return None
    return "\n".join(part for part in (instruction, facts) if part), output


SHAPES = {
    "column": shape_column,
    "chat_reply": shape_chat_reply,
    "subject_body": shape_subject_body,
    "translation": shape_translation,
    "nli": shape_nli,
    "finqa": shape_finqa,
    "invoice_ocr": shape_invoice_ocr,
    "instruction_input": shape_instruction_input,
}


def text_of(value: Any) -> str:
    if value is None:
        return ""
    return (value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)).strip()


def json_of(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def table_text(table: Any) -> str:
    rows = json_of(table)
    if not isinstance(rows, list):
        return ""
    return "\n".join(" | ".join(str(cell) for cell in row) for row in rows if isinstance(row, list))


# --------------------------------------------------------------------------- #
# a set
# --------------------------------------------------------------------------- #


def build(spec: dict[str, Any]) -> list[dict[str, Any]]:
    shape = SHAPES.get(spec.get("fetch", "column"))
    if shape is None:
        raise FetchError(f"{spec['name']}: unknown fetch shape {spec.get('fetch')!r}")

    wanted = int(spec["rows"])
    cap = int(spec.get("max_input_chars", 8000))
    floor = int(spec.get("min_expected_chars", 1))
    slug = spec["name"].split(":", 1)[-1]
    examples: list[dict[str, Any]] = []
    seen: set[str] = set()

    for offset in range(0, wanted * WINDOW, PAGE):
        for row in fetch_page(spec, offset):
            made = shape(row, spec)
            if made is None:
                continue
            text, expected = made
            # A one-line answer under a long input is usually a signature or a
            # stub, and grading a real reply against it scores the corpus.
            if len(str(expected)) < floor or len(text) > cap or text in seen:
                continue
            seen.add(text)
            examples.append(
                {
                    "id": f"{slug}-{len(examples) + 1:04d}",
                    "input": text,
                    "expected": expected,
                    "graders": list(spec.get("graders") or []),
                    "tags": ["business-catalogue", slug],
                }
            )
            if len(examples) >= wanted:
                return examples
    return examples


def write(spec: dict[str, Any], examples: list[dict[str, Any]]) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{spec['name'].split(':', 1)[-1]}.jsonl"
    path.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in examples), encoding="utf-8"
    )
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("match", nargs="*", help="only sets whose name contains one of these")
    parser.add_argument("--check", action="store_true", help="fetch and report, write nothing")
    args = parser.parse_args()

    catalogue = yaml.safe_load(CATALOGUE.read_text(encoding="utf-8"))
    specs = [
        spec
        for spec in catalogue["sets"]
        if not args.match or any(term in spec["name"] for term in args.match)
    ]
    if not specs:
        print("No set matched.", file=sys.stderr)
        return 1

    failures = 0
    for spec in specs:
        name = spec["name"]
        try:
            examples = build(spec)
        except FetchError as exc:
            print(f"FAIL {name}: {exc}", file=sys.stderr)
            failures += 1
            continue
        if not examples:
            print(f"FAIL {name}: no usable rows from {spec['source']}", file=sys.stderr)
            failures += 1
            continue
        short = len(examples) < int(spec["rows"])
        if args.check:
            print(f"{'WARN' if short else 'OK  '} {name}: {len(examples)} rows (not written)")
            continue
        path = write(spec, examples)
        size = path.stat().st_size / 1024
        print(
            f"{'WARN' if short else 'OK  '} {name}: {len(examples)} rows, "
            f"{size:.0f} KiB -> {path.relative_to(ROOT)}"
        )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
