"""Textual-facing: the prompt widget. Typing ! in an empty prompt enters shell mode for one submission."""

import shlex
import sys

from textual.document._editing import EditingMode
from toad.prompt_actions import CompleteShellPathAction
from toad.conversation_actions import InterruptAction
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


async def test_the_remapped_interrupt_stops_the_running_shell_without_quitting(workspace):
    async with workspace.app(binding=AgentAttached(peer("echo"))) as ui:
        await ui.until_agent_ready()
        app, _ = ui.textual
        view = ui.conversation
        app.set_keymap({InterruptAction.binding_id(EditingMode): "f7"})
        assert not view.check_action("interrupt", ())
        await ui.press("exclamation_mark")
        program = "import time; print(chr(10) + 'SHELL_INTERRUPT_READY', flush=True); time.sleep(30)"
        await ui.type(f"{shlex.quote(sys.executable)} -c {shlex.quote(program)}")
        await ui.press("enter")
        await ui.until(lambda: view.can_interrupt_command, why="the live shell to accept interruption")
        terminal = view._terminal
        assert terminal is not None
        await ui.until(lambda: any(line.content.plain.strip() == "SHELL_INTERRUPT_READY"
                                   for line in terminal.state.buffer.lines),
                       why="the child process to write its ready line")
        view.window.focus()
        await ui.press("f7")
        async def command_finished():
            return not await view.shell.is_busy()
        await ui.until(command_finished, why="the remapped interrupt to stop the child process")
        assert not app._exit
        assert not workspace.prompts_received(), "Shell input must not be sent to the agent"
