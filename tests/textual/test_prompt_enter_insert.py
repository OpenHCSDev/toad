"""Textual-facing: vim `i` asks the prompt for insert mode; the prompt owns whether its editor exists."""

from agent_comms.repo import Checkout
from support.agents import peer
from toad.key_modes import Standard, VimInsert
from toad.preferences import SETTINGS
from toad.screens.settings import SettingsScreen
from toad.session_scope import AgentAttached
from toad.widgets.prompt import MessagePrompt


def test_enter_insert_before_compose_has_no_editor_to_touch(tmp_path):
    MessagePrompt(project=Checkout(tmp_path)).enter_insert()


async def test_real_neovim_submission_shrinks_document_and_cursor_together(workspace):
    async with workspace.app(binding=AgentAttached(peer("echo"))) as ui:
        await ui.until_agent_ready()
        app = ui.app
        prompt = ui.conversation.prompt
        area = prompt.prompt_text_area
        app.saved_settings.set(SETTINGS.ui.key_mode, VimInsert)
        await ui.until(lambda: area.key_mode is VimInsert,
                       why="the declared Neovim insert profile")
        await ui.until(lambda: area.editing_mode.completed,
                       why="the real child to finish its initial document")
        area.focus()
        await ui.type("first")
        await ui.press("shift+enter")
        await ui.type("second")
        await ui.until(lambda: (area.text == "first\nsecond"
                                and area.cursor_location == (1, 6)
                                and area.editing_mode.completed),
                       why="the real second-line cursor before submission")
        await ui.press("enter")
        await ui.until(lambda: workspace.prompts_received() == ["first\nsecond"],
                       why="the actual private peer to receive the submitted text")
        await ui.until(lambda: (area.text == "" and area.cursor_location == (0, 0)
                                and area.editing_mode.completed),
                       why="the cleared document and cursor to publish together")
        await ui.type("still here")
        await ui.until(lambda: area.text == "still here" and area.editing_mode.completed,
                       why="the same prompt to accept input after shrinking")
        await ui.press("ctrl+c")
        await ui.until(lambda: area.text == "" and area.editing_mode.completed,
                       why="the local clear command, not the yielding app quit hint")


async def test_standard_chooser_retires_neovim_and_saved_selection_reopens(workspace):
    async with workspace.app() as ui:
        app = ui.app
        prompt = ui.conversation.prompt
        area = prompt.prompt_text_area
        app.saved_settings.set(SETTINGS.ui.key_mode, VimInsert)
        await ui.until(lambda: area.key_mode is VimInsert,
                       why="the declared Neovim profile")
        await ui.until(lambda: area.editing_mode.completed,
                       why="a completed real child before selecting Standard")
        previous = area.editing_mode._child
        area.focus()
        await ui.type("retained draft")
        await ui.until(lambda: area.text == "retained draft" and area.editing_mode.completed,
                       why="a real draft to transfer to the native editor")
        await ui.press("ctrl+comma")
        await ui.until(lambda: isinstance(app.screen, SettingsScreen),
                       why="the application settings binding before Neovim")
        await ui.until(lambda: str(SETTINGS.ui.key_mode) in app.screen.form.values,
                       why="the existing declared mode chooser")
        chooser = app.screen.form.values[str(SETTINGS.ui.key_mode)].editor
        assert chooser.lists(Standard)
        chooser.value = Standard
        await ui.until(lambda: app.settings.ui.key_mode is Standard and area.key_mode is Standard,
                       why="Standard selected through the real settings editor")
        assert previous.returncode is not None
        assert area.text == "retained draft"
        await ui.press("escape")
        await ui.until(lambda: app.screen is app.workspace_screen and not app.saved_settings.unsaved,
                       why="the selected profile saved after closing settings")
        area.focus()
        await ui.until(lambda: str(prompt.editing_mode_label.render()) == Standard.label,
                       why="the visible Standard label at the focused native editor")
        await ui.type(" kept")
        assert area.text == "retained draft kept"
        app.saved_settings.set(SETTINGS.ui.key_mode, VimInsert)
        await ui.until(lambda: area.key_mode is VimInsert,
                       why="returning to the declared engine profile")
        await ui.until(lambda: area.editing_mode.completed,
                       why="the new generation's real child and transferred draft")
        current = area.editing_mode._child
        assert current.identity != previous.identity
        assert current.returncode is None
        assert area.text == "retained draft kept"
        app.saved_settings.set(SETTINGS.ui.key_mode, Standard)
        await ui.until(lambda: area.key_mode is Standard,
                       why="retiring the second child through the same mode owner")
        assert current.returncode is not None
        await app.saved_settings.save()
    async with workspace.app() as ui:
        await ui.until(lambda: ui.conversation.prompt.prompt_text_area.key_mode is Standard,
                       why="the actual saved Standard preference after reopen")
        area = ui.conversation.prompt.prompt_text_area
        area.focus()
        await ui.until(lambda: str(ui.conversation.prompt.editing_mode_label.render()) == Standard.label,
                       why="the saved Standard label, without starting the engine")
