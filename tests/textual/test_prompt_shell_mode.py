"""Textual-facing: the prompt widget. Typing ! in an empty prompt enters shell mode for one submission."""

from textual.document._editing import EditingMode
from toad.prompt_actions import CompleteShellPathAction
from support.agents import peer
from toad.session_scope import AgentAttached
from toad.widgets.prompt import Prompt


async def test_shell_mode_runs_one_command_then_returns_to_agent_input(workspace):
    async with workspace.app(binding=AgentAttached(peer("echo"))) as ui:
        await ui.until_agent_ready()
        app, _pilot = ui.textual
        prompt = app.selected_session.query_one(Prompt)
        await ui.press("exclamation_mark")
        await ui.until(lambda: prompt.shell_mode, why="! to enter shell mode")
        assert prompt.shell_mode and ui.draft() == ""
        await ui.type("echo SHELL_RAN")
        await ui.press("enter")
        await ui.until(lambda: not prompt.shell_mode, why="shell mode to end after one command")
        await ui.until_shows("SHELL_RAN")
        await ui.type("open again")
        await ui.press("enter")
        await ui.until(lambda: workspace.prompts_received() == ["open again"], why="the next input at the agent")


async def test_shell_path_completion_remaps_and_cursor_movement_clears_stale_suggestions(workspace):
    (workspace.project / "alpha.txt").touch()
    (workspace.project / "alpine.txt").touch()
    async with workspace.app() as ui:
        app, _ = ui.textual
        app.set_keymap({CompleteShellPathAction.binding_id(EditingMode): "f6"})
        await ui.press("exclamation_mark")
        await ui.type("cat alp")
        editor = ui.conversation.prompt.prompt_text_area
        await ui.press("f6")
        await ui.until(lambda: editor.suggestions is not None, why="shell path suggestions")
        assert len(editor.suggestions) == 2
        first = editor.suggestion
        await ui.press("f6")
        assert editor.suggestion != first
        await ui.press("left")
        assert editor.suggestions is None and editor.suggestion == ""
