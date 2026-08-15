from __future__ import annotations

import pytest

from prompt_playoff.dataset_store import DatasetStore, decode_name, encode_name
from prompt_playoff.evals import BenchmarkExample
from prompt_playoff.registry import Registry
from prompt_playoff.service import PromptSelectorService


def examples(*inputs: str) -> list[BenchmarkExample]:
    return [
        BenchmarkExample(id=f"e{index}", input=text, expected=f"gold {index}")
        for index, text in enumerate(inputs, 1)
    ]


@pytest.mark.parametrize(
    "name",
    [
        "hf:Tobi-Bueck/customer-support-tickets",
        "uploaded:my-tickets",
        "hf:owner/name with spaces",
        "hf:owner/100%-coverage",
        "плохое:имя/тоже",
    ],
)
def test_names_survive_the_round_trip_through_a_filename(name):
    encoded = encode_name(name)
    assert "/" not in encoded
    assert decode_name(encoded) == name


def test_save_then_load_returns_the_same_examples(tmp_path):
    store = DatasetStore(tmp_path)
    store.save("hf:acme/reviews", examples("first", "second"))

    reloaded = DatasetStore(tmp_path).load()
    assert list(reloaded) == ["hf:acme/reviews"]
    assert [item.input for item in reloaded["hf:acme/reviews"]] == ["first", "second"]
    assert [item.expected for item in reloaded["hf:acme/reviews"]] == ["gold 1", "gold 2"]


def test_saved_file_is_plain_jsonl(tmp_path):
    store = DatasetStore(tmp_path)
    path = store.save("hf:acme/reviews", examples("first", "second"))
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("{") and lines[0].endswith("}")


def test_saving_the_same_name_twice_replaces_it(tmp_path):
    store = DatasetStore(tmp_path)
    store.save("hf:acme/reviews", examples("first", "second"))
    store.save("hf:acme/reviews", examples("only one"))
    reloaded = DatasetStore(tmp_path).load()
    assert [item.input for item in reloaded["hf:acme/reviews"]] == ["only one"]


def test_load_of_a_missing_directory_is_empty_not_an_error(tmp_path):
    assert DatasetStore(tmp_path / "nothing-here").load() == {}


def test_one_unreadable_file_does_not_hide_the_others(tmp_path):
    store = DatasetStore(tmp_path)
    store.save("hf:acme/good", examples("fine"))
    (tmp_path / "hf%3Aacme%2Fbroken.jsonl").write_text("{not json at all\n", encoding="utf-8")

    loaded = store.load()
    assert list(loaded) == ["hf:acme/good"]
    # The bytes are kept for diagnosis rather than silently dropped.
    assert len(store.corrupt) == 1
    assert store.corrupt[0].name.startswith("hf%3Aacme%2Fbroken.jsonl.corrupt-")
    assert not (tmp_path / "hf%3Aacme%2Fbroken.jsonl").exists()
    assert store.recovery_warning and ".corrupt-" in store.recovery_warning


def test_no_recovery_warning_when_everything_read_cleanly(tmp_path):
    store = DatasetStore(tmp_path)
    store.save("hf:acme/good", examples("fine"))
    store.load()
    assert store.recovery_warning is None


def test_remove_reports_whether_there_was_anything_to_remove(tmp_path):
    store = DatasetStore(tmp_path)
    store.save("hf:acme/reviews", examples("first"))
    assert store.remove("hf:acme/reviews") is True
    assert store.remove("hf:acme/reviews") is False


# --------------------------------------------------------------------------- #
# the service side: what survives a restart and what does not
# --------------------------------------------------------------------------- #


def service(tmp_path) -> PromptSelectorService:
    return PromptSelectorService(Registry.load(), datasets=DatasetStore(tmp_path))


def test_a_persisted_dataset_comes_back_in_a_new_service(tmp_path):
    first = service(tmp_path)
    first.add_user_dataset("hf:acme/reviews", examples("first"), persist=True)

    second = service(tmp_path)
    assert "hf:acme/reviews" in second.dataset_names
    assert [item.input for item in second.dataset("hf:acme/reviews")] == ["first"]


def test_a_dataset_added_without_persist_is_gone_after_a_restart(tmp_path):
    first = service(tmp_path)
    first.add_user_dataset("uploaded:mine", examples("first"))
    assert "uploaded:mine" in first.dataset_names

    second = service(tmp_path)
    assert "uploaded:mine" not in second.dataset_names


def test_persisting_reports_where_it_went(tmp_path):
    path = service(tmp_path).add_user_dataset("hf:acme/reviews", examples("first"), persist=True)
    assert path is not None
    assert path.parent == tmp_path
    assert path.exists()


def test_the_packaged_datasets_are_still_listed_alongside_saved_ones(tmp_path):
    saved = service(tmp_path)
    saved.add_user_dataset("hf:acme/reviews", examples("first"), persist=True)
    names = service(tmp_path).dataset_names
    assert "gsm8k" in names
    assert "hf:acme/reviews" in names
