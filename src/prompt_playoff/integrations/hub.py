"""Find examples for a task on the Hugging Face Hub, without leaving the app.

The Hub's ``search`` parameter matches a substring of the dataset **name**, not
its contents, so handing it a sentence-long task description returns nothing at
all. Everything here exists to bridge that gap: turn the description into the
two- and three-word names people actually give datasets, run several of those
queries, and merge what comes back.

Two public services are used, neither of which needs a token:

* ``huggingface.co/api/datasets`` — the catalogue, for names, downloads and tags.
* ``datasets-server.huggingface.co`` — column names and rows, so a candidate can
  be previewed and imported without downloading the corpus or pulling in
  ``datasets`` and ``pyarrow``.

The module is split so the parts that decide anything stay pure: query building,
column guessing and row conversion are ordinary functions over plain data, and
only three thin coroutines touch the network.
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
from pydantic import BaseModel, Field

from prompt_playoff.domain import CompiledPrompt, Message, ModelProfile, TaskType
from prompt_playoff.graders import is_free_text
from prompt_playoff.providers import ModelProvider, ProviderError, provider_for

HUB_API = "https://huggingface.co/api/datasets"
ROWS_API = "https://datasets-server.huggingface.co"

#: The Hub pages rows at 100; asking for more in one request is refused.
ROWS_PAGE = 100
MAX_IMPORT_ROWS = 500


class HubError(RuntimeError):
    """The Hub could not answer. Always carries what to tell the user."""


# --------------------------------------------------------------------------- #
# what a search returns
# --------------------------------------------------------------------------- #


class HubCandidate(BaseModel):
    dataset: str
    downloads: int = 0
    likes: int = 0
    task_categories: list[str] = Field(default_factory=list)
    size_category: str = ""
    summary: str = ""
    url: str = ""
    #: Which of our queries found it, so a suspicious hit can be traced back.
    matched: list[str] = Field(default_factory=list)


class HubColumn(BaseModel):
    name: str
    dtype: str
    #: ClassLabel columns store integers; these are the names they stand for.
    labels: list[str] = Field(default_factory=list)


class HubPreview(BaseModel):
    dataset: str
    config: str
    split: str
    configs: list[str] = Field(default_factory=list)
    splits: list[str] = Field(default_factory=list)
    columns: list[HubColumn] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    suggested_input: str | None = None
    suggested_expected: str | None = None
    notes: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# description -> queries (pure)
# --------------------------------------------------------------------------- #

#: Dataset names are English even when the request is not, so every task type
#: seeds the search with the words the Hub actually uses for it.
TASK_QUERIES: dict[TaskType, tuple[str, ...]] = {
    TaskType.structured_extraction: ("entity extraction", "ner", "information extraction"),
    TaskType.classification: ("classification", "intent", "sentiment"),
    TaskType.translation: ("translation", "parallel corpus"),
    TaskType.coding: ("code generation", "python programs", "humaneval"),
    TaskType.research: ("question answering", "retrieval qa"),
    TaskType.agents: ("tool use", "function calling", "agent trajectories"),
    TaskType.summarization: ("summarization", "abstractive summary"),
    TaskType.creative_writing: ("story generation", "creative writing"),
}

#: The Hub's own task vocabulary, used as a filter alongside the name search.
TASK_CATEGORIES: dict[TaskType, str] = {
    TaskType.structured_extraction: "token-classification",
    TaskType.classification: "text-classification",
    TaskType.translation: "translation",
    TaskType.coding: "text-generation",
    TaskType.research: "question-answering",
    TaskType.agents: "text-generation",
    TaskType.summarization: "summarization",
    TaskType.creative_writing: "text-generation",
}

_STOPWORDS = frozenset(
    """
    a an and are as at be but by do for from has have in into is it its me my not of on or our
    that the their them then there these this to up us was we were what when which who will with
    without you your please make sure never always must should each every all any some only just
    text texts model models output outputs input inputs result results answer answers task tasks
    """.split()
)

_WORD = re.compile(r"[a-z][a-z-]{2,}")


def keyword_queries(description: str, task_type: TaskType | None = None) -> list[str]:
    """Short, name-like search terms from a description, without a model.

    Deliberately crude: the Hub matches substrings of names, so a long or
    inventive phrase is worse than a common two-word one.

    Order is the ranking signal, so the user's own subject matter goes first and
    the task type's generic terms last. Those generic terms match the most
    downloaded corpora on the Hub, and leading with them buries the specific
    hit under a pile of famous ones. They stay in the list because a Russian or
    otherwise non-Latin description yields no words here at all.
    """
    words = [word for word in _WORD.findall(description.lower()) if word not in _STOPWORDS]
    # Pairs name a subject ("customer support"); a lone word names anything that
    # merely contains it, so "extract" drags in every repo with Extracted in its
    # name. Pairs lead, the task type's known-good terms come next, and single
    # words rank last, where they can still rescue a search that found nothing.
    queries = [f"{first} {second}" for first, second in zip(words, words[1:], strict=False)][:3]
    queries += list(TASK_QUERIES[task_type]) if task_type else []
    queries += words[:3]
    return _dedupe(queries)[:8]


def generic_queries(task_type: TaskType | None) -> set[str]:
    """The terms this module supplies itself, as opposed to the user's subject."""
    return set(TASK_QUERIES[task_type]) if task_type else set()


def generic_result_note(
    queries: list[str], candidates: list[HubCandidate], task_type: TaskType | None
) -> str | None:
    """Say how much of this list came from the task type rather than the subject.

    The failure this catches is silent. The catalogue matches a term against
    dataset **names**, so a real subject nobody has named a dataset after —
    "spain economy" — returns nothing, while the generic term added as a safety
    net returns the most downloaded corpora on the Hub. What the user sees is a
    full page of plausible datasets with no sign that none of them came from
    anything they said.

    Counted rather than all-or-nothing: a single word from the description
    ("spain") matches something almost always, and a list can be three real hits
    ranked under six that only answer the task type.
    """
    generic = generic_queries(task_type)
    if not candidates or not generic:
        return None
    own = [query for query in queries if query not in generic]
    if not own:
        return None
    from_generic = [item for item in candidates if not set(item.matched) - generic]
    if not from_generic:
        return None
    # The terms themselves are listed directly underneath, so naming them twice
    # would bury the one thing this sentence exists to say.
    used = [query for query in queries if query in generic]
    plural = "terms" if len(used) > 1 else "term"
    blamed = f"{_quoted(used)}, the general {plural} for this kind of task"
    tail = "The catalogue searches dataset names, not their contents."
    if len(from_generic) == len(candidates):
        return (
            "Nothing on the Hub is named after your subject: no term describing it matched a "
            f"dataset name. Every result below was found by {blamed}. {tail}"
        )
    return (
        f"{len(from_generic)} of the {len(candidates)} results below were found only by {blamed}, "
        f"not by anything describing your subject. {tail}"
    )


ENGINE_SYSTEM = (
    "You turn a task description into search terms for the Hugging Face dataset catalogue. "
    "The catalogue matches your term against dataset NAMES only, so terms must look like "
    "parts of a dataset name: one to three common English words, lowercase, no punctuation, "
    'no sentences. Answer with JSON: {"queries": ["...", "..."]}'
)


def engine_request(description: str) -> str:
    return (
        "Task description:\n"
        f"{description.strip()}\n\n"
        "Give 3 to 5 search terms that would appear in the name of a dataset holding "
        "examples of this exact work. Prefer the plainest naming people use, and include "
        "the subject matter, not only the technique."
    )


def parse_queries(content: str) -> list[str]:
    """Pull the query list out of whatever shape the model answered with."""
    payload = _json_object(content)
    raw = payload.get("queries") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        return []
    cleaned: list[str] = []
    for item in raw:
        text = " ".join(str(item).lower().split())
        text = re.sub(r"[^a-z0-9 -]", "", text).strip()
        # Four words or more stops being a name and starts being a sentence.
        if text and len(text.split()) <= 3:
            cleaned.append(text)
    return _dedupe(cleaned)[:6]


async def search_queries(
    description: str,
    task_type: TaskType | None = None,
    engine: ModelProfile | None = None,
    provider: ModelProvider | None = None,
    timeout_seconds: float = 60,
) -> tuple[list[str], str]:
    """Queries for this description, and which path produced them.

    The engine model is asked first because it can name the subject matter in
    English however the request was written. Every failure — no engine, provider
    down, prose instead of JSON — lands on :func:`keyword_queries`, and the
    caller is told which happened rather than being left to guess.
    """
    fallback = keyword_queries(description, task_type)
    if engine is None:
        return fallback, "keywords"
    prompt = CompiledPrompt(
        technique_id="hub.search",
        stage="search",
        messages=[
            Message(role="system", content=ENGINE_SYSTEM),
            Message(role="user", content=engine_request(description)),
        ],
        generation_options={"temperature": 0.0},
    )
    try:
        result = await (provider or provider_for(engine)).generate(prompt, engine, timeout_seconds)
    except ProviderError:
        return fallback, "keywords"
    proposed = parse_queries(result.content)
    if not proposed:
        return fallback, "keywords"
    # The task type's own terms stay in the list: they are the ones known to
    # match real dataset names when the model's guesses are inventive.
    seed = list(TASK_QUERIES[task_type])[:1] if task_type else []
    return _dedupe([*proposed, *seed])[:6], "engine"


# --------------------------------------------------------------------------- #
# columns and rows -> benchmark examples (pure)
# --------------------------------------------------------------------------- #

_INPUT_NAMES = (
    "input", "text", "question", "prompt", "sentence", "article", "document",
    "content", "source", "query", "premise", "dialogue", "utterance", "review",
    "body", "instruction", "passage",
)  # fmt: skip

_EXPECTED_NAMES = (
    "expected", "answer", "label", "output", "target", "summary", "translation",
    "completion", "response", "gold", "category", "intent", "class", "sentiment",
    "highlights", "labels", "tags", "abstract",
)  # fmt: skip


def read_columns(features: list[dict[str, Any]]) -> list[HubColumn]:
    columns: list[HubColumn] = []
    for feature in features:
        spec = feature.get("type") or {}
        kind = str(spec.get("_type") or "")
        dtype = str(spec.get("dtype") or kind or "unknown")
        labels = [str(name) for name in (spec.get("names") or [])] if kind == "ClassLabel" else []
        columns.append(HubColumn(name=str(feature.get("name", "")), dtype=dtype, labels=labels))
    return [column for column in columns if column.name]


def suggest_columns(
    columns: list[HubColumn], rows: list[dict[str, Any]]
) -> tuple[str | None, str | None]:
    """Guess which column is the model's input and which is the right answer.

    Name first, because dataset authors are consistent about it. When names say
    nothing, the longest text becomes the input and a short-valued neighbour the
    answer, which is the shape nearly every text dataset has.
    """
    names = [column.name for column in columns]
    if not names:
        return None, None

    def by_name(candidates: tuple[str, ...], skip: str | None) -> str | None:
        for wanted in candidates:
            for name in names:
                if name != skip and name.lower() == wanted:
                    return name
        for wanted in candidates:
            for name in names:
                if name != skip and wanted in name.lower():
                    return name
        return None

    lengths = {name: _mean_length(rows, name) for name in names}
    source = by_name(_INPUT_NAMES, None)
    if source is None:
        source = max(names, key=lambda name: lengths[name])
    expected = by_name(_EXPECTED_NAMES, source)
    if expected is None:
        others = [name for name in names if name != source]
        # Anything left that is shorter than the input is a plausible answer;
        # a longer column is more likely a second passage than a label.
        shorter = [name for name in others if lengths[name] <= lengths[source]]
        expected = min(shorter, key=lambda name: lengths[name]) if shorter else None
    return source, expected


def graders_for(expected: list[Any]) -> list[str]:
    """Name the graders for an imported column, from the shape of its answers.

    An import has no dataset card to declare graders, so without this every
    string answer falls back to exact match. That is right for a label column
    and meaningless for a column of abstracts or translations: no paraphrase
    reproduces a reference verbatim, so the score is a certain 0 that reads as
    a failed prompt.

    The whole column decides, not each row, so one short answer among long ones
    cannot make half the dataset graded on a different scale.
    """
    values = [item for item in expected if item is not None]
    if not values:
        return []
    if any(isinstance(item, (dict, list)) for item in values):
        return ["field_f1", "exact_match"]
    prose = sum(1 for item in values if is_free_text(item))
    if prose * 2 > len(values):
        return ["token_f1"]
    return ["label_accuracy", "exact_match"]


def to_examples(
    rows: list[dict[str, Any]],
    columns: list[HubColumn],
    dataset: str,
    input_column: str,
    expected_column: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Rows as they come off the Hub -> benchmark examples.

    Rows with an empty input are dropped rather than scored: an example the
    model cannot answer measures the dataset, not the prompt.
    """
    slug = dataset.split("/")[-1].lower()
    label_names = {column.name: column.labels for column in columns if column.labels}
    examples: list[dict[str, Any]] = []
    for index, row in enumerate(rows, 1):
        text = _as_text(row.get(input_column))
        if not text:
            continue
        example: dict[str, Any] = {
            "id": f"{slug}-{index:04d}",
            "input": text,
            "tags": ["huggingface", slug],
        }
        if expected_column:
            expected = _as_expected(row.get(expected_column), label_names.get(expected_column, []))
            if expected is None:
                continue
            example["expected"] = expected
        examples.append(example)
        if len(examples) >= limit:
            break

    # Written into every example rather than left to the defaults, so the saved
    # JSONL says on its face how it will be scored.
    graders = graders_for([item.get("expected") for item in examples])
    for example in examples:
        if graders:
            example["graders"] = list(graders)
    return examples


# --------------------------------------------------------------------------- #
# the three coroutines that touch the network
# --------------------------------------------------------------------------- #


async def search(
    queries: list[str],
    task_type: TaskType | None = None,
    limit: int = 12,
    per_query: int = 6,
    transport: httpx.AsyncBaseTransport | None = None,
    timeout_seconds: float = 30,
) -> list[HubCandidate]:
    """Run every query against the catalogue and merge the hits.

    Ranking follows the caller's query order first: the term closest to what the
    user actually described beats a famous corpus that a generic term dragged
    in. Only within one query does agreement between queries, and then download
    count, decide.
    """
    category = TASK_CATEGORIES.get(task_type) if task_type else None
    found: dict[str, HubCandidate] = {}
    rank: dict[str, int] = {}
    async with httpx.AsyncClient(timeout=timeout_seconds, transport=transport) as client:
        for position, query in enumerate(queries):
            params: dict[str, Any] = {
                "search": query,
                "limit": per_query,
                "sort": "downloads",
                "direction": -1,
            }
            if category:
                params["filter"] = f"task_categories:{category}"
            payload = await _get_json(client, HUB_API, params)
            if not isinstance(payload, list):
                continue
            for item in payload:
                candidate = _candidate(item)
                if candidate is None:
                    continue
                existing = found.get(candidate.dataset)
                if existing is None:
                    candidate.matched = [query]
                    found[candidate.dataset] = candidate
                    rank[candidate.dataset] = position
                elif query not in existing.matched:
                    existing.matched.append(query)
    ranked = sorted(
        found.values(),
        key=lambda item: (rank[item.dataset], -len(item.matched), -item.downloads),
    )
    return ranked[:limit]


async def preview(
    dataset: str,
    config: str | None = None,
    split: str | None = None,
    rows: int = 3,
    transport: httpx.AsyncBaseTransport | None = None,
    timeout_seconds: float = 30,
) -> HubPreview:
    """Columns, a few real rows, and a guess at which column is which."""
    async with httpx.AsyncClient(timeout=timeout_seconds, transport=transport) as client:
        listing = await _get_json(client, f"{ROWS_API}/splits", {"dataset": dataset})
        entries = listing.get("splits") if isinstance(listing, dict) else None
        if not entries:
            raise HubError(
                f"{dataset} has no readable splits. The Hub's dataset viewer is off for it, "
                "so its rows cannot be fetched here — download it yourself and upload a JSONL."
            )
        configs = _dedupe([str(entry.get("config", "")) for entry in entries])
        chosen_config = config or _preferred(configs, ("default", "main", "en"))
        splits = _dedupe(
            [
                str(entry.get("split", ""))
                for entry in entries
                if str(entry.get("config", "")) == chosen_config
            ]
        )
        chosen_split = split or _preferred(splits, ("validation", "test", "train"))
        payload = await _get_json(
            client,
            f"{ROWS_API}/first-rows",
            {"dataset": dataset, "config": chosen_config, "split": chosen_split},
        )

    columns = read_columns(payload.get("features") or [])
    sample = [dict(item.get("row") or {}) for item in (payload.get("rows") or [])][:rows]
    source, expected = suggest_columns(columns, sample)
    notes: list[str] = []
    if expected is None:
        notes.append(
            "No column looks like a right answer. Imported without one, the run still "
            "measures format and stability, but not whether the answers are correct."
        )
    else:
        notes.append(_grading_note(expected, [row.get(expected) for row in sample]))
    return HubPreview(
        dataset=dataset,
        config=chosen_config,
        split=chosen_split,
        configs=configs,
        splits=splits,
        columns=columns,
        rows=sample,
        suggested_input=source,
        suggested_expected=expected,
        notes=notes,
    )


async def fetch_rows(
    dataset: str,
    config: str,
    split: str,
    limit: int,
    transport: httpx.AsyncBaseTransport | None = None,
    timeout_seconds: float = 60,
) -> tuple[list[dict[str, Any]], list[HubColumn]]:
    """Read up to ``limit`` rows, paging as the Hub requires."""
    wanted = max(1, min(limit, MAX_IMPORT_ROWS))
    rows: list[dict[str, Any]] = []
    columns: list[HubColumn] = []
    async with httpx.AsyncClient(timeout=timeout_seconds, transport=transport) as client:
        while len(rows) < wanted:
            payload = await _get_json(
                client,
                f"{ROWS_API}/rows",
                {
                    "dataset": dataset,
                    "config": config,
                    "split": split,
                    "offset": len(rows),
                    "length": min(ROWS_PAGE, wanted - len(rows)),
                },
            )
            if not columns:
                columns = read_columns(payload.get("features") or [])
            page = [dict(item.get("row") or {}) for item in (payload.get("rows") or [])]
            if not page:
                break
            rows += page
    return rows[:wanted], columns


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


async def _get_json(client: httpx.AsyncClient, url: str, params: dict[str, Any]) -> Any:
    try:
        response = await client.get(url, params=params)
    except httpx.HTTPError as exc:
        raise HubError(
            f"Could not reach the Hugging Face Hub ({exc.__class__.__name__}). "
            "Searching needs an internet connection; everything else here works offline."
        ) from exc
    if response.status_code >= 400:
        raise HubError(f"The Hub answered {response.status_code} for {url}: {_detail(response)}")
    try:
        return response.json()
    except ValueError as exc:
        raise HubError(f"The Hub answered {url} with something that is not JSON.") from exc


def _detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:200] or response.reason_phrase
    if isinstance(payload, dict):
        return str(payload.get("error") or payload.get("detail") or payload)[:200]
    return str(payload)[:200]


def _candidate(item: Any) -> HubCandidate | None:
    if not isinstance(item, dict) or not item.get("id"):
        return None
    tags = [str(tag) for tag in (item.get("tags") or [])]
    modalities = [tag.split(":", 1)[1] for tag in tags if tag.startswith("modality:")]
    # Image and audio corpora cannot be fed to a text prompt; showing them wastes
    # the one decision the user has to make here.
    if modalities and "text" not in modalities:
        return None
    if item.get("private") or item.get("gated") or item.get("disabled"):
        return None
    sizes = [tag.split(":", 1)[1] for tag in tags if tag.startswith("size_categories:")]
    return HubCandidate(
        dataset=str(item["id"]),
        downloads=int(item.get("downloads") or 0),
        likes=int(item.get("likes") or 0),
        task_categories=[
            tag.split(":", 1)[1] for tag in tags if tag.startswith("task_categories:")
        ],
        size_category=sizes[0] if sizes else "",
        summary=_summary(str(item.get("description") or "")),
        url=f"https://huggingface.co/datasets/{item['id']}",
    )


def _summary(description: str) -> str:
    text = " ".join(description.split())
    # Card descriptions open with the repo's own heading repeated as prose; the
    # first sentence after it is the only part that says what the data is.
    cut = text.split(". ")
    first = cut[0] if cut else text
    return (first[:240] + "…") if len(first) > 240 else first


def _grading_note(column: str, values: list[Any]) -> str:
    """Say how this column will be scored, while the choice can still be changed.

    Without grader names: the reader is deciding whether this is the right
    column, and needs the consequence of the choice, not its implementation.
    """
    graders = graders_for(values)
    if not graders:
        return f"No row in the sample has a value in {column!r}."
    if "token_f1" in graders:
        return (
            f"Answers in {column!r} are whole sentences, so a run is scored on how much of "
            "the reference wording it recovers. Comparing sentences whole would score every "
            "honest rewording 0."
        )
    if "field_f1" in graders:
        return (
            f"Answers in {column!r} are structured, so a run is scored item by item: "
            "getting 3 of 4 right scores 0.86, not 0."
        )
    return (
        f"Answers in {column!r} are short labels, so a run is scored on matching the "
        "reference exactly."
    )


def _preferred(values: list[str], order: tuple[str, ...]) -> str:
    for wanted in order:
        if wanted in values:
            return wanted
    return values[0] if values else ""


def _quoted(values: list[str]) -> str:
    """A readable list of terms: 'a', 'b' and 'c'."""
    quoted = [repr(value) for value in values]
    if len(quoted) < 2:
        return "".join(quoted)
    return f"{', '.join(quoted[:-1])} and {quoted[-1]}"


def _dedupe(values: list[str]) -> list[str]:
    return [value for value in dict.fromkeys(values) if value]


def _mean_length(rows: list[dict[str, Any]], column: str) -> float:
    lengths = [len(_as_text(row.get(column))) for row in rows]
    return sum(lengths) / len(lengths) if lengths else 0.0


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    return json.dumps(value, ensure_ascii=False)


def _as_expected(value: Any, labels: list[str]) -> Any | None:
    """The gold answer, with ClassLabel integers resolved to their names.

    A dataset that stores "positive" as 1 would otherwise ask the model to
    output the number 1, which is a property of the storage format and nothing
    the prompt can be blamed for.
    """
    if value is None:
        return None
    numeric_label = isinstance(value, int) and not isinstance(value, bool)
    if labels and numeric_label and 0 <= int(value) < len(labels):
        return labels[int(value)]
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, (int, float, bool, list, dict)):
        return value
    return str(value)


def _json_object(content: str) -> dict[str, Any]:
    """The first JSON object in the answer, or an empty one."""
    text = content.strip()
    for candidate in (text, *re.findall(r"\{.*?\}", text, flags=re.S)):
        try:
            parsed = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}
