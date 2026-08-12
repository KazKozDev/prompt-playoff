from pathlib import Path

from prompt_playoff.evals import load_jsonl

DATASETS = Path(__file__).parents[1] / "src" / "prompt_playoff" / "data" / "datasets"


def test_uncovered_datasets_have_deterministic_headroom_shape():
    expected_graders = {
        "translation": {"glossary_consistency", "omission_check"},
        "summarization": {"contains_all", "length_limit"},
        "grounded-qa": {"grounding_overlap", "contains_all"},
        "agents": {"tool_success", "exact_match"},
    }
    for name, graders in expected_graders.items():
        rows = load_jsonl(DATASETS / f"{name}.jsonl")
        assert len(rows) >= 100
        assert len({row.id for row in rows}) == len(rows)
        assert len({row.input for row in rows}) == len(rows)
        assert all(set(row.graders) == graders for row in rows)


def test_translation_gold_and_glossary_follow_from_source():
    for row in load_jsonl(DATASETS / "translation.jsonl"):
        glossary = row.grader_options["glossary"]
        source = row.grader_options["source"]
        assert all(term in source for term in glossary)
        assert all(term in row.expected for term in glossary.values())


def test_summaries_require_only_verbatim_document_facts():
    for row in load_jsonl(DATASETS / "summarization.jsonl"):
        assert all(fact in row.input for fact in row.grader_options["contains"])


def test_grounded_qa_includes_unsettled_cases():
    rows = load_jsonl(DATASETS / "grounded-qa.jsonl")
    unsettled = [row for row in rows if "unsettled" in row.tags]
    assert len(unsettled) >= 20
    assert all(row.expected == "INSUFFICIENT_EVIDENCE" for row in unsettled)


def test_agent_gold_is_recomputable():
    rows = load_jsonl(DATASETS / "agents.jsonl")
    assert {tag for row in rows for tag in row.tags} >= {"calculator", "word-count"}
    for row in rows:
        if "word-count" in row.tags:
            text = row.input.split("text: ", 1)[1].split(" Return only", 1)[0]
            assert row.expected == str(len(text.rstrip(".").split()))
