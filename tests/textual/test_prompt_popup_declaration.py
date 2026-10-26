"""Textual-facing: a popup class declared by subclassing mounts in every full prompt, paints, takes focus,
returns focus on Escape, and is absent from the simple composer."""

from textual.app import ComposeResult
from textual.widgets import Input

from support.textual_steps import painted_text
from toad.widgets.prompt import Prompt
from toad.widgets.prompt_popup import CompletionPopup, PromptPopup


class ReviewPopup(CompletionPopup):
    DEFAULT_CSS = "ReviewPopup { overlay: screen; offset-y: -3; height: 3; }"

    @classmethod
    def for_prompt(cls, prompt):
        return None if prompt.simple_input else cls()

    def compose_content(self) -> ComposeResult:
        yield Input(placeholder="DECLARED_NEW_POPUP_PAINT")

    def focus_content(self, scroll_visible):
        self.query_one(Input).focus(scroll_visible=False)


async def test_a_declared_popup_paints_and_returns_focus_to_the_draft(workspace):
    async with workspace.app(size=(110, 38)) as ui:
        prompt = ui.conversation.prompt
        await ui.until(lambda: prompt.query(ReviewPopup), why="the declared popup in the prompt")
        popup = prompt.query_one(ReviewPopup)
        assert ReviewPopup in CompletionPopup.members_with(CompletionPopup)
        prompt.text = "Draft retained"
        popup.focus()
        await ui.until(lambda: (entry := popup.query_one_optional(Input)) is not None and entry.has_focus, why="focus in the popup")
        await ui.until(lambda: painted_text(popup, "DECLARED_NEW_POPUP_PAINT"), why="the popup painted")
        await ui.press("escape")
        await ui.until(lambda: not popup.is_open and prompt.prompt_text_area.has_focus, why="focus back in the draft")
        assert prompt.text == "Draft retained"


async def test_the_simple_composer_has_no_declared_popup_and_takes_a_slash_as_text(workspace):
    async with workspace.app(size=(110, 38)) as ui:
        app, _pilot = ui.textual
        simple = Prompt(simple_input=True)
        await app.screen.mount(simple)
        await ui.step()
        assert not simple.query(ReviewPopup)
        simple.focus()
        await ui.press("/")
        assert simple.text == "/" and simple.prompt_text_area.has_focus
        assert all(not widget.is_open for widget in simple.query(PromptPopup))
        assert ui.failure() is None
