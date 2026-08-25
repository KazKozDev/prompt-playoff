"""A prompt can be taken back out, and taking it out stops there.

Everything in the composer created or rewrote; there was no way to end up with
nothing. Writing a second prompt meant typing over the first and pressing
Create, which left the first one's scorecard, matrix and judge verdict sitting
on their screens — numbers about a prompt that existed nowhere. And a release
row could only be moved along the line, never removed, so a name typed twice
stayed in the register forever saying something that was never true.

These are the assertions that keep both deletions honest: that they remove what
they claim to, and that they stop at what they claim to.
"""

from pathlib import Path

STATIC = Path(__file__).parents[1] / "src/prompt_playoff/data/static"


def read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def delete_prompt_body() -> str:
    selector = read("selector.js")
    start = selector.index("function deletePrompt()")
    return selector[start : selector.index("\n}", start)]


def test_the_composer_offers_a_delete_only_while_it_is_holding_something():
    """A Delete button over an empty composer acts on nothing."""
    selector = read("selector.js")
    assert "function renderPromptDelete()" in selector
    body = selector[
        selector.index("function renderPromptDelete()") : selector.index("function deletePrompt()")
    ]
    assert "state.program || state.chosen" in body
    assert "host.hidden = !holding" in body


def test_the_delete_is_armed_before_it_fires():
    """One click destroys work no measurement can bring back.

    The same two-step a dataset gets, held in state for the same reason: these
    controls are written from state, so a confirm that lives on the button is a
    confirm the next redraw quietly takes back.
    """
    selector = read("selector.js")
    core = read("core.js")
    assert "pendingPromptDelete:false" in core
    assert 'data-action="delete-prompt-arm"' in selector
    assert 'data-action="delete-prompt-now"' in selector
    assert 'data-action="delete-prompt-cancel"' in selector


def test_deleting_the_prompt_takes_every_number_measured_on_it():
    """A scorecard left behind is a number about a prompt with no text to read."""
    body = delete_prompt_body()
    for cleared in ("state.program", "state.chosen", "state.ranking", "state.provenance"):
        assert f"{cleared} = null" in body or f"{cleared} = []" in body
    assert "state.report = state.comparison = state.optimization = null" in body
    # The judge verdict and the model matrix are the same leftover, held on the
    # platform screens rather than in the composer's own state.
    assert "q.results = {}" in body
    assert "forgetDraft();" in body


def test_deleting_the_prompt_leaves_the_history_and_the_register_alone():
    """A recorded run is a measurement that happened; deleting the prompt does
    not un-happen it. A release froze its own copy of the text and goes on being
    the record of something that shipped."""
    body = delete_prompt_body()
    assert "state.experiments" not in body
    assert "q.releases" not in body
    assert "/v1/experiments" not in body
    assert "/v1/releases" not in body
    # Ship is not redrawn for the same reason: nothing on it changed.
    selector = read("selector.js")
    screens = selector[selector.index("const PROMPT_DEPENDENT_SCREENS") :]
    screens = screens[: screens.index(";")]
    assert "'ship'" not in screens
    for tab in ("prompt", "report", "comparison", "optimization", "results", "judge"):
        assert f"'{tab}'" in screens


def test_the_screens_already_drawn_are_redrawn_after_a_delete():
    """They are drawn once and left alone, so clearing state does not reach them.

    Without this the deleted prompt is still readable on the screen it was
    deleted from, and the band on the four screens that carry it goes on
    quoting a prompt that no longer exists.
    """
    body = delete_prompt_body()
    assert "PROMPT_DEPENDENT_SCREENS.forEach" in body
    assert "dataset.rendered = 'false'" in body
    assert "renderDetail();" in body


def test_a_release_row_can_be_taken_out_of_the_register():
    platform = read("platform.js")
    core = read("core.js")
    assert "function releaseDeleteControl(release)" in platform
    assert "${releaseDeleteControl(item)}" in platform
    assert "pendingReleaseDelete:null" in core
    assert "data-release-delete-arm" in platform
    assert "data-release-delete-now" in platform
    assert "data-release-delete-cancel" in platform
    assert "'DELETE'" in platform


def test_deleting_the_production_release_says_what_it_costs_first():
    """It is the app's answer to "what is live". Taking it out leaves no answer,
    and no earlier version to roll back to."""
    platform = read("platform.js")
    control = platform[
        platform.index("function releaseDeleteControl(release)") : platform.index(
            "/* The frozen text itself"
        )
    ]
    assert "release.status === 'production'" in control
    assert "nothing to roll back to" in control
