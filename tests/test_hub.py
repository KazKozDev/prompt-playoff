from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from prompt_playoff.api import app
from prompt_playoff.dataset_store import DatasetStore
from prompt_playoff.domain import ModelProfile, ModelResult, TaskType
from prompt_playoff.integrations import hub
from prompt_playoff.providers import ProviderError

# --------------------------------------------------------------------------- #
# query building
# --------------------------------------------------------------------------- #


def test_keyword_queries_lead_with_the_subject_then_the_task_type():
    queries = hub.keyword_queries(
        "Classify incoming customer support tickets by urgency", TaskType.classification
    )
    assert queries[0] == "classify incoming"
    assert "customer support" in queries
    # The generic term sits behind every pair the description supplied: leading
    # with it buries the specific hit under the Hub's most downloaded corpora.
    assert queries.index("customer support") < queries.index("classification")
    # Single words rank last, where they can only rescue an empty search.
    assert queries.index("classification") < queries.index("classify")


def test_keyword_queries_fall_back_to_the_task_type_for_a_non_latin_description():
    queries = hub.keyword_queries("Кратко пересказать новостную статью", TaskType.summarization)
    assert queries == list(hub.TASK_QUERIES[TaskType.summarization])


def test_keyword_queries_without_a_task_type_use_only_the_description():
    assert hub.keyword_queries("translate legal contracts") == [
        "translate legal",
        "legal contracts",
        "translate",
        "legal",
        "contracts",
    ]


def test_parse_queries_keeps_name_shaped_terms_only():
    content = """Here you go:
    {"queries": ["Customer Support!", "a whole sentence that is far too long to be a name",
                 "customer support", "ticket triage"]}"""
    assert hub.parse_queries(content) == ["customer support", "ticket triage"]


def test_parse_queries_survives_prose():
    assert hub.parse_queries("I would search for customer support datasets.") == []


class _EngineProvider:
    def __init__(self, content: str) -> None:
        self.content = content

    async def generate(self, prompt, model, timeout_seconds: float = 120):
        return ModelResult(content=self.content, usage={})


class _DeadProvider:
    async def generate(self, prompt, model, timeout_seconds: float = 120):
        raise ProviderError("engine is down")


ENGINE = ModelProfile(provider="ollama", model_id="engine-model", local=True)


@pytest.mark.asyncio
async def test_search_queries_prefer_the_engine():
    queries, source = await hub.search_queries(
        "Разметить обращения в поддержку",
        TaskType.classification,
        engine=ENGINE,
        provider=_EngineProvider('{"queries": ["support tickets", "helpdesk"]}'),
    )
    assert source == "engine"
    assert queries[:2] == ["support tickets", "helpdesk"]
    # One known-good term for the task type stays, in case the model invented names.
    assert hub.TASK_QUERIES[TaskType.classification][0] in queries


@pytest.mark.asyncio
async def test_search_queries_fall_back_when_the_engine_is_unreachable():
    queries, source = await hub.search_queries(
        "classify support tickets",
        TaskType.classification,
        engine=ENGINE,
        provider=_DeadProvider(),
    )
    assert source == "keywords"
    assert queries == hub.keyword_queries("classify support tickets", TaskType.classification)


@pytest.mark.asyncio
async def test_search_queries_fall_back_when_the_engine_answers_with_prose():
    queries, source = await hub.search_queries(
        "classify support tickets",
        TaskType.classification,
        engine=ENGINE,
        provider=_EngineProvider("I think you want customer service data."),
    )
    assert source == "keywords"
    assert queries == hub.keyword_queries("classify support tickets", TaskType.classification)


@pytest.mark.asyncio
async def test_search_queries_without_an_engine_never_calls_a_model():
    queries, source = await hub.search_queries("classify support tickets")
    assert source == "keywords"
    assert queries


# --------------------------------------------------------------------------- #
# columns and conversion
# --------------------------------------------------------------------------- #


def test_read_columns_resolves_class_label_names():
    columns = hub.read_columns(
        [
            {"name": "text", "type": {"dtype": "string", "_type": "Value"}},
            {"name": "label", "type": {"names": ["neg", "pos"], "_type": "ClassLabel"}},
        ]
    )
    assert [column.name for column in columns] == ["text", "label"]
    assert columns[1].labels == ["neg", "pos"]
    assert columns[1].dtype == "ClassLabel"


def test_suggest_columns_reads_the_names_first():
    columns = [
        hub.HubColumn(name="id", dtype="string"),
        hub.HubColumn(name="question", dtype="string"),
        hub.HubColumn(name="answer", dtype="string"),
    ]
    rows = [{"id": "1", "question": "How many?", "answer": "4"}]
    assert hub.suggest_columns(columns, rows) == ("question", "answer")


def test_suggest_columns_falls_back_to_the_longest_text():
    columns = [
        hub.HubColumn(name="alpha", dtype="string"),
        hub.HubColumn(name="beta", dtype="string"),
    ]
    rows = [{"alpha": "x" * 200, "beta": "short"}]
    assert hub.suggest_columns(columns, rows) == ("alpha", "beta")


def test_suggest_columns_reports_no_answer_column_when_there_is_one_column():
    columns = [hub.HubColumn(name="text", dtype="string")]
    assert hub.suggest_columns(columns, [{"text": "hello"}]) == ("text", None)


def test_to_examples_resolves_labels_and_drops_unusable_rows():
    columns = [
        hub.HubColumn(name="text", dtype="string"),
        hub.HubColumn(name="label", dtype="ClassLabel", labels=["neg", "pos"]),
    ]
    rows = [
        {"text": "loved it", "label": 1},
        {"text": "   ", "label": 0},
        {"text": "hated it", "label": 0},
        {"text": "no answer here", "label": None},
    ]
    examples = hub.to_examples(rows, columns, "acme/reviews", "text", "label", limit=10)
    assert [item["input"] for item in examples] == ["loved it", "hated it"]
    # A stored 1 means "pos"; asking the model to answer 1 would measure the
    # storage format rather than the prompt.
    assert [item["expected"] for item in examples] == ["pos", "neg"]
    assert examples[0]["id"] == "reviews-0001"
    assert examples[0]["tags"] == ["huggingface", "reviews"]


def test_to_examples_without_an_expected_column_keeps_the_inputs():
    columns = [hub.HubColumn(name="text", dtype="string")]
    rows = [{"text": "one"}, {"text": "two"}]
    examples = hub.to_examples(rows, columns, "acme/x", "text", None, limit=10)
    assert [item["input"] for item in examples] == ["one", "two"]
    assert all("expected" not in item for item in examples)


def test_to_examples_scores_a_label_column_by_exact_match():
    columns = [
        hub.HubColumn(name="text", dtype="string"),
        hub.HubColumn(name="label", dtype="ClassLabel", labels=["neg", "pos"]),
    ]
    rows = [{"text": "loved it", "label": 1}, {"text": "hated it", "label": 0}]
    examples = hub.to_examples(rows, columns, "acme/reviews", "text", "label", limit=10)
    assert all(item["graders"] == ["label_accuracy", "exact_match"] for item in examples)


def test_to_examples_scores_a_prose_column_by_word_overlap():
    """The bug this guards: a summary column silently graded by exact match.

    Every honest summary then scores 0, and the run reports a broken prompt
    where the only thing broken was the metric.
    """
    columns = [
        hub.HubColumn(name="article", dtype="string"),
        hub.HubColumn(name="abstract", dtype="string"),
    ]
    rows = [
        {
            "article": f"A long paper about liquid crystals, part {index}.",
            "abstract": "We report a nematic phase transition observed in a thin film "
            f"of the compound under an applied field, at sample {index}.",
        }
        for index in range(3)
    ]
    examples = hub.to_examples(rows, columns, "ccdv/arxiv-summarization", "article", "abstract", 10)
    assert all(item["graders"] == ["token_f1"] for item in examples)


def test_to_examples_grades_a_mixed_column_one_way_for_every_row():
    columns = [hub.HubColumn(name="q", dtype="string"), hub.HubColumn(name="a", dtype="string")]
    rows = [{"q": "one", "a": "yes"}] + [
        {"q": f"row {index}", "a": "A full sentence of prose that runs well past the label length."}
        for index in range(4)
    ]
    examples = hub.to_examples(rows, columns, "acme/x", "q", "a", limit=10)
    assert {tuple(item["graders"]) for item in examples} == {("token_f1",)}


def test_to_examples_honours_the_limit():
    columns = [hub.HubColumn(name="text", dtype="string")]
    rows = [{"text": f"row {index}"} for index in range(50)]
    assert len(hub.to_examples(rows, columns, "acme/x", "text", None, limit=7)) == 7


# --------------------------------------------------------------------------- #
# the network calls, against a fake Hub
# --------------------------------------------------------------------------- #


def hub_item(name: str, downloads: int = 0, tags: list[str] | None = None, **extra: Any) -> dict:
    return {"id": name, "downloads": downloads, "tags": tags or ["modality:text"], **extra}


def catalogue(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_search_ranks_by_query_order_then_agreement():
    def respond(request: httpx.Request) -> httpx.Response:
        query = request.url.params["search"]
        if query == "customer support":
            return httpx.Response(200, json=[hub_item("acme/support-tickets", 12)])
        return httpx.Response(
            200,
            json=[hub_item("famous/corpus", 900_000), hub_item("acme/support-tickets", 12)],
        )

    found = await hub.search(["customer support", "classification"], transport=catalogue(respond))
    # Popularity does not rescue a dataset that only the generic term found.
    assert [item.dataset for item in found] == ["acme/support-tickets", "famous/corpus"]
    assert found[0].matched == ["customer support", "classification"]


@pytest.mark.asyncio
async def test_search_drops_what_cannot_be_used_as_text_examples():
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                hub_item("acme/pictures", 10, tags=["modality:image"]),
                hub_item("acme/locked", 10, gated=True),
                hub_item("acme/hidden", 10, private=True),
                hub_item(
                    "acme/usable", 10, tags=["modality:text", "task_categories:summarization"]
                ),
            ],
        )

    found = await hub.search(["anything"], transport=catalogue(respond))
    assert [item.dataset for item in found] == ["acme/usable"]
    assert found[0].task_categories == ["summarization"]


@pytest.mark.asyncio
async def test_search_passes_the_task_category_as_a_filter():
    seen: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params.get("filter", ""))
        return httpx.Response(200, json=[])

    await hub.search(["x"], TaskType.summarization, transport=catalogue(respond))
    assert seen == ["task_categories:summarization"]


@pytest.mark.asyncio
async def test_search_reports_an_unreachable_hub_in_words():
    def respond(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    with pytest.raises(hub.HubError, match="internet connection"):
        await hub.search(["x"], transport=catalogue(respond))


SPLITS = {
    "splits": [
        {"dataset": "acme/qa", "config": "default", "split": "train"},
        {"dataset": "acme/qa", "config": "default", "split": "validation"},
        {"dataset": "acme/qa", "config": "other", "split": "train"},
    ]
}

FIRST_ROWS = {
    "features": [
        {"name": "question", "type": {"dtype": "string", "_type": "Value"}},
        {"name": "answer", "type": {"dtype": "string", "_type": "Value"}},
    ],
    "rows": [{"row": {"question": "How many?", "answer": "4"}}],
}


@pytest.mark.asyncio
async def test_preview_picks_a_held_out_split_and_guesses_the_columns():
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/splits"):
            return httpx.Response(200, json=SPLITS)
        assert request.url.params["split"] == "validation"
        return httpx.Response(200, json=FIRST_ROWS)

    preview = await hub.preview("acme/qa", transport=catalogue(respond))
    assert (preview.config, preview.split) == ("default", "validation")
    assert preview.configs == ["default", "other"]
    assert preview.splits == ["train", "validation"]
    assert (preview.suggested_input, preview.suggested_expected) == ("question", "answer")
    assert "matching the reference exactly" in preview.notes[0]


@pytest.mark.asyncio
async def test_preview_says_how_a_prose_column_will_be_scored():
    """How the answers are graded is a decision, so it is shown before the import."""

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/splits"):
            return httpx.Response(200, json=SPLITS)
        return httpx.Response(
            200,
            json={
                "features": [
                    {"name": "article", "type": {"dtype": "string", "_type": "Value"}},
                    {"name": "abstract", "type": {"dtype": "string", "_type": "Value"}},
                ],
                "rows": [
                    {
                        "row": {
                            "article": "A paper about galaxy clusters and their haloes. " * 40,
                            "abstract": "We measure the mass function of clusters at high "
                            "redshift and compare it against the standard model.",
                        }
                    }
                ],
            },
        )

    preview = await hub.preview("acme/papers", transport=catalogue(respond))
    assert preview.suggested_expected == "abstract"
    assert "reference wording" in preview.notes[0]
    # The reader is choosing a column, not a grader: the note says what the
    # choice costs them, and names no implementation.
    assert not any(name in preview.notes[0] for name in ("token_f1", "field_f1", "exact_match"))


@pytest.mark.asyncio
async def test_preview_says_so_when_no_column_holds_a_right_answer():
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/splits"):
            return httpx.Response(200, json=SPLITS)
        return httpx.Response(
            200,
            json={
                "features": [{"name": "text", "type": {"dtype": "string", "_type": "Value"}}],
                "rows": [{"row": {"text": "hello"}}],
            },
        )

    preview = await hub.preview("acme/qa", transport=catalogue(respond))
    assert preview.suggested_expected is None
    assert "not whether the answers are correct" in preview.notes[0]


@pytest.mark.asyncio
async def test_preview_explains_a_dataset_with_the_viewer_switched_off():
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"splits": []})

    with pytest.raises(hub.HubError, match="dataset viewer is off"):
        await hub.preview("acme/private", transport=catalogue(respond))


@pytest.mark.asyncio
async def test_fetch_rows_pages_until_it_has_enough():
    pages: list[int] = []

    def respond(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params["offset"])
        length = int(request.url.params["length"])
        pages.append(length)
        return httpx.Response(
            200,
            json={
                "features": FIRST_ROWS["features"],
                "rows": [
                    {"row": {"question": f"q{offset + i}", "answer": "4"}} for i in range(length)
                ],
            },
        )

    rows, columns = await hub.fetch_rows(
        "acme/qa", "default", "train", 150, transport=catalogue(respond)
    )
    assert len(rows) == 150
    assert pages == [100, 50]
    assert [column.name for column in columns] == ["question", "answer"]


@pytest.mark.asyncio
async def test_fetch_rows_stops_when_the_split_runs_out():
    def respond(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params["offset"])
        rows = [] if offset else [{"row": {"question": "q", "answer": "4"}}]
        return httpx.Response(200, json={"features": FIRST_ROWS["features"], "rows": rows})

    rows, _ = await hub.fetch_rows("acme/qa", "default", "train", 100, transport=catalogue(respond))
    assert len(rows) == 1


# --------------------------------------------------------------------------- #
# the endpoints
# --------------------------------------------------------------------------- #


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_hub_search_endpoint_returns_candidates_and_the_queries_it_used(client, monkeypatch):
    async def fake_search(queries, task_type=None, **kwargs):
        return [hub.HubCandidate(dataset="acme/support-tickets", downloads=12, matched=queries[:1])]

    monkeypatch.setattr(hub, "search", fake_search)
    response = client.post(
        "/v1/datasets/hub/search",
        json={"description": "classify customer support tickets", "task_type": "classification"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "keywords"
    assert "customer support" in payload["queries"]
    assert payload["candidates"][0]["dataset"] == "acme/support-tickets"


def test_hub_search_endpoint_warns_when_only_the_generic_term_found_anything(client, monkeypatch):
    """The real failure from a summarization search for 'forecast for Spain'.

    Four terms naming the subject matched no dataset name, the task type's own
    term matched the most downloaded corpora on the Hub, and the six results
    that came back had nothing to do with the request.
    """

    async def fake_search(queries, task_type=None, **kwargs):
        return [
            hub.HubCandidate(
                dataset="ccdv/arxiv-summarization", downloads=8743, matched=["summarization"]
            ),
            hub.HubCandidate(
                dataset="ccdv/pubmed-summarization", downloads=5104, matched=["summarization"]
            ),
        ]

    monkeypatch.setattr(hub, "search", fake_search)
    response = client.post(
        "/v1/datasets/hub/search",
        json={
            "description": "forecast for spain economic development",
            "task_type": "summarization",
        },
    )
    note = response.json()["notes"][0]
    assert note.startswith("Nothing on the Hub is named after your subject")
    assert "searches dataset names, not their contents" in note
    assert "'summarization'" in note
    # The terms are listed directly under this line; repeating them here would
    # bury the sentence in its own evidence.
    assert "spain" not in note


def test_hub_search_endpoint_counts_the_generic_hits_among_real_ones(client, monkeypatch):
    """One real hit ranked among generic ones is still worth saying out loud."""

    async def fake_search(queries, task_type=None, **kwargs):
        return [
            hub.HubCandidate(dataset="ccdv/arxiv-summarization", matched=["summarization"]),
            hub.HubCandidate(dataset="acme/spain-economy", matched=["spain economy"]),
        ]

    monkeypatch.setattr(hub, "search", fake_search)
    response = client.post(
        "/v1/datasets/hub/search",
        json={"description": "spain economy outlook", "task_type": "summarization"},
    )
    assert response.json()["notes"][0].startswith("1 of the 2 results")


def test_hub_search_endpoint_stays_quiet_when_every_hit_came_from_the_subject(client, monkeypatch):
    async def fake_search(queries, task_type=None, **kwargs):
        return [hub.HubCandidate(dataset="acme/spain-economy", matched=["spain economy"])]

    monkeypatch.setattr(hub, "search", fake_search)
    response = client.post(
        "/v1/datasets/hub/search",
        json={"description": "spain economy outlook", "task_type": "summarization"},
    )
    assert response.json()["notes"] == []


def test_generic_result_note_needs_a_task_type_to_have_a_fallback_to_blame():
    candidates = [hub.HubCandidate(dataset="acme/x", matched=["anything"])]
    assert hub.generic_result_note(["anything"], candidates, None) is None
    assert hub.generic_result_note(["summarization"], [], TaskType.summarization) is None


def test_hub_search_endpoint_surfaces_a_hub_outage_as_502(client, monkeypatch):
    async def fake_search(queries, task_type=None, **kwargs):
        raise hub.HubError("Could not reach the Hugging Face Hub (ConnectError).")

    monkeypatch.setattr(hub, "search", fake_search)
    response = client.post("/v1/datasets/hub/search", json={"description": "anything at all"})
    assert response.status_code == 502
    assert "Could not reach" in response.json()["detail"]


def test_hub_import_registers_a_dataset_and_keeps_it_on_disk(client, monkeypatch):
    columns = [
        hub.HubColumn(name="text", dtype="string"),
        hub.HubColumn(name="label", dtype="ClassLabel", labels=["neg", "pos"]),
    ]

    async def fake_fetch(dataset, config, split, limit, **kwargs):
        return [{"text": f"review {index}", "label": index % 2} for index in range(limit)], columns

    monkeypatch.setattr(hub, "fetch_rows", fake_fetch)
    response = client.post(
        "/v1/datasets/hub/import",
        json={
            "dataset": "acme/reviews",
            "config": "default",
            "split": "test",
            "input_column": "text",
            "expected_column": "label",
            "limit": 5,
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "hf:acme/reviews"
    assert body["examples"] == 5
    assert body["has_expected"] == 5

    # It has to arrive on the same named-dataset path every measurement uses.
    listed = {item["name"] for item in client.get("/v1/datasets").json()}
    assert "hf:acme/reviews" in listed
    rows = client.get("/v1/datasets/hf:acme/reviews").json()
    assert rows[0]["expected"] == "neg"
    assert rows[0]["tags"] == ["huggingface", "reviews"]

    # Public rows the user spent a download and a set of column choices on are
    # written out, so the next server start still has them.
    saved = Path(body["saved_to"])
    assert saved.exists()
    reloaded = DatasetStore(saved.parent).load()
    assert [item.input for item in reloaded["hf:acme/reviews"]] == [
        f"review {index}" for index in range(5)
    ]


def test_uploaded_examples_are_not_written_to_disk(client, tmp_path, monkeypatch):
    """A file from the user's own machine is not persisted without being asked."""
    monkeypatch.setenv("PROMPT_PLAYOFF_DATASETS", str(tmp_path / "datasets"))
    body = json.dumps({"id": "1", "input": "private note", "expected": "hi"})
    response = client.post(
        "/v1/datasets/upload", files={"file": ("mine.jsonl", body, "application/jsonl")}
    )
    assert response.status_code == 201
    assert not list(tmp_path.glob("datasets/*.jsonl"))


def test_hub_import_rejects_a_column_the_dataset_does_not_have(client, monkeypatch):
    async def fake_fetch(dataset, config, split, limit, **kwargs):
        return [{"text": "one"}], [hub.HubColumn(name="text", dtype="string")]

    monkeypatch.setattr(hub, "fetch_rows", fake_fetch)
    response = client.post(
        "/v1/datasets/hub/import",
        json={
            "dataset": "acme/reviews",
            "config": "default",
            "split": "test",
            "input_column": "nope",
            "limit": 5,
        },
    )
    assert response.status_code == 422
    assert "has no input column 'nope'" in response.json()["detail"]


def test_hub_import_rejects_a_split_with_nothing_usable(client, monkeypatch):
    async def fake_fetch(dataset, config, split, limit, **kwargs):
        return [{"text": "   "}], [hub.HubColumn(name="text", dtype="string")]

    monkeypatch.setattr(hub, "fetch_rows", fake_fetch)
    response = client.post(
        "/v1/datasets/hub/import",
        json={
            "dataset": "acme/reviews",
            "config": "default",
            "split": "test",
            "input_column": "text",
            "limit": 5,
        },
    )
    assert response.status_code == 422
    assert "No usable rows" in response.json()["detail"]


def test_hub_preview_endpoint_passes_the_chosen_config_through(client, monkeypatch):
    seen: dict[str, Any] = {}

    async def fake_preview(dataset, config=None, split=None, **kwargs):
        seen.update(dataset=dataset, config=config, split=split)
        return hub.HubPreview(dataset=dataset, config=config or "default", split=split or "train")

    monkeypatch.setattr(hub, "preview", fake_preview)
    response = client.get(
        "/v1/datasets/hub/preview", params={"dataset": "acme/qa", "config": "en", "split": "test"}
    )
    assert response.status_code == 200
    assert seen == {"dataset": "acme/qa", "config": "en", "split": "test"}
    assert response.json()["split"] == "test"


def test_uploaded_json_still_round_trips(client):
    """The Hub path must not disturb the plain upload it shares a home with."""
    body = json.dumps({"id": "1", "input": "hello", "expected": "hi"})
    response = client.post(
        "/v1/datasets/upload", files={"file": ("mine.jsonl", body, "application/jsonl")}
    )
    assert response.status_code == 201
    assert response.json()["name"] == "uploaded:mine"
