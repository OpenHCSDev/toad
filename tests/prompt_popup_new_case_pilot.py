"""A new declared popup mounts and shares lifetime without any consumer edit."""
import asyncio
from importlib.resources import files
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from textual.app import ComposeResult
from textual.widgets import Input

from runtime_fixture import ToadApp
from sidebar_retirement_pilot import until, viewport_text
from toad.widgets.prompt import Prompt
from toad.widgets.prompt_popup import CompletionPopup, PromptPopup


class ReviewPopup(CompletionPopup):
    DEFAULT_CSS = "ReviewPopup { overlay: screen; offset-y: -3; height: 3; }"

    @classmethod
    def for_prompt(cls, prompt):
        return None if prompt.simple_input else cls()

    def compose(self) -> ComposeResult:
        yield Input(placeholder="DECLARED_NEW_POPUP_PAINT")

    def focus_content(self, scroll_visible):
        self.query_one(Input).focus(scroll_visible=False)


class InstalledApp(ToadApp):
    CSS_PATH = files("toad").joinpath("toad.tcss")


async def main():
    with TemporaryDirectory(prefix="popup-declaration-", dir=os.environ["TMPDIR"]) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        app = InstalledApp(project_dir=str(root))
        async with app.run_test(size=(110, 38)) as pilot:
            prompt = app.selected_session.conversation.prompt
            popup = prompt.query_one(ReviewPopup)
            assert PromptPopup.decode(ReviewPopup.declared_name) is ReviewPopup
            prompt.text = "Draft retained"
            popup.focus()
            await until(pilot, lambda: popup.query_one(Input).has_focus)
            await until(pilot, lambda: popup in app.screen._compositor.visible_widgets and
                        "DECLARED_NEW_POPUP_PAINT" in viewport_text(popup))
            await pilot.press("escape")
            await until(pilot, lambda: not popup.is_open and prompt.prompt_text_area.has_focus)
            assert prompt.text == "Draft retained"
            simple = Prompt(simple_input=True)
            await app.screen.mount(simple)
            await pilot.pause(.02)
            assert not simple.query(ReviewPopup)
            simple.focus()
            await pilot.press("/")
            await pilot.pause(.02)
            assert simple.text == "/" and simple.prompt_text_area.has_focus
            assert all(not widget.is_open for widget in simple.query(PromptPopup))
            assert app._exception is None
            print("INSTALLED_DECLARATION_ONLY_NEW_POPUP_PAINT_ESCAPE_DRAFT_AND_SIMPLE_COMPOSER_PASS", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
