"""The prompt is openable at every step, and outlives the tab that wrote it.

The compiled prompt used to exist in exactly one place — page memory, drawn on
one screen — and every other surface described it instead of showing it: the
measurement column faded out after 260 characters, the run history stores a
preview and a fingerprint, and the release register stores a fingerprint alone.
A reload emptied the one screen that had it, and nothing anywhere could produce
the text again. These are the assertions that keep each of those routes open.
"""

from pathlib import Path

from prompt_playoff.api import _release_prompt_text

STATIC = Path(__file__).parents[1] / "src/prompt_playoff/data/static"


def read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


COMPILED = {
    "technique_id": "reasoning.rephrase-and-respond",
    "stages": [
        {
            "stage": "main",
            "messages": [
                {"role": "system", "content": "Extract people and places as strict JSON."},
                {"role": "user", "content": "REPHRASE\nRestate the task in your own words."},
            ],
        }
    ],
}


def test_a_release_manifest_carries_the_prompt_as_text():
    """`prompt.text` is the wording, not a serialized object.

    The workbench registers a compiled program, and that shape fell through every
    branch of the reader to the JSON dump at the end — so the one file meant to
    carry the exact wording out of this tool carried it in the least readable
    form the tool can produce.
    """
    text = _release_prompt_text(COMPILED)
    assert text.startswith("SYSTEM\nExtract people and places as strict JSON.")
    assert "REPHRASE\nRestate the task in your own words." in text
    assert "technique_id" not in text


def test_a_multi_call_release_names_the_call_each_message_belongs_to():
    prompt = {
        "stages": [
            {"stage": "draft", "messages": [{"role": "user", "content": "First."}]},
            {"stage": "revise", "messages": [{"role": "user", "content": "Second."}]},
        ]
    }
    text = _release_prompt_text(prompt)
    assert "draft · USER\nFirst." in text
    assert "revise · USER\nSecond." in text


def test_a_payload_that_is_not_a_compiled_prompt_still_reads_out():
    assert _release_prompt_text({"text": "Just the words."}) == "Just the words."
    loose = {"messages": [{"role": "user", "content": "Hello"}]}
    assert "user: Hello" in _release_prompt_text(loose)
    assert '"unknown"' in _release_prompt_text({"unknown": 1})


def test_the_draft_is_written_down_and_read_back_before_the_first_render():
    core = read("core.js")
    boot = read("boot.js")
    navigation = read("navigation.js")
    assert "function rememberDraft()" in core
    assert "function restoreDraft()" in core
    # Every path that changes the prompt ends in a render, so the draft is
    # written from there rather than from each of those paths.
    assert "rememberDraft();" in navigation[navigation.index("function renderDetail()") :]
    # Read back before anything draws, or the screens draw an empty prompt and
    # correct themselves a frame later.
    assert boot.index("restoreDraft();") < boot.index("initializeNavigation();")


def test_the_draft_never_carries_a_credential_to_disk():
    """`state.task` holds the evaluation profile, and that holds an API key."""
    core = read("core.js")
    saved = core[core.index("function rememberDraft()") : core.index("function forgetDraft()")]
    assert "state.task" not in saved
    assert "settings" not in saved


def test_the_column_beside_a_measurement_opens_the_whole_prompt():
    measurements = read("measurements.js")
    assert "function subjectFullText()" in measurements
    assert "${subjectFullText()}" in measurements
    # The fade stays as the glance; it is no longer the only text on the screen.
    assert "opening.slice(0, 260)" in measurements


def test_a_release_row_opens_the_text_its_fingerprint_stands_for():
    platform = read("platform.js")
    styles = read("styles.css")
    assert "function releasePromptRow(release)" in platform
    assert "${releasePromptRow(item)}" in platform
    assert 'data-release-text="${esc(item.id)}"' in platform
    assert "[data-release-text]" in platform
    assert ".link-hash" in styles


def test_one_implementation_draws_a_whole_prompt():
    """Two screens show the same prompt; neither walks the stages itself."""
    core = read("core.js")
    assert core.count("function promptMessages(program)") == 1
    for name in ("measurements.js", "platform.js"):
        javascript = read(name)
        assert "promptMessages(" in javascript
        assert "promptPartBlock" in javascript


def test_the_two_readers_of_a_frozen_prompt_know_the_same_shapes():
    """A release freezes whatever payload registered it.

    The screen showing that payload and the manifest exporting it are two
    readers of one record; a shape only one of them knows is a release that
    reads as a prompt in the file and as a JSON object on the screen.
    """
    core = read("core.js")
    start = core.index("function promptMessages(program)")
    reader = core[start : core.index("const promptPlainText")]
    for key in ("text", "prompt", "content"):
        assert f"'{key}'" in reader
    assert "program?.messages" in reader
    assert "program?.stages" in reader
