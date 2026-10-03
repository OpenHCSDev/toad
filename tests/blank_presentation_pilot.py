"""Actual retained editors and session-owned shells survive physical tab returns."""

import asyncio
from importlib.resources import files
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from runtime_fixture import ToadApp
from native_session_retention_pilot import conversation_paint
from textual.widgets.text_area import Selection

from toad.widgets.conversation import Conversation
from toad.widgets.prompt import PromptTextArea
from toad.widgets.session_tabs import SessionLabel
from toad.widgets.side_bar import SideBar
from toad.screens.main import MainScreen
from toad.shell_output import ShellTerminalOutput
from toad.widgets.shell_result import ShellResult
from toad.core.input_events import UserInputSubmitted


class InstalledApp(ToadApp):
    CSS_PATH = files("toad").joinpath("toad.tcss")


async def select(app, pilot, source):
    label = app.screen.query_one(f"SessionLabel#{source.id}", SessionLabel)
    label.scroll_visible(animate=False, immediate=True)
    await pilot.pause()
    assert await pilot.click(label)
    await pilot.pause()
    assert app.selected_session is source


async def main():
    with TemporaryDirectory(prefix="toad-session-surface-", dir=os.environ["TMPDIR"]) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        app = InstalledApp(project_dir=str(root))
        async with app.run_test(size=(100, 35)) as pilot:
            await pilot.pause()
            first = app.selected_session
            first_surface = first.conversation
            original_task = first_surface._task
            window = first_surface.window
            viewport = window.document_viewport
            assert window in first.viewport_presentation.windows
            editor = first.conversation.prompt.prompt_text_area
            editor.insert("first draft")
            editor.history.checkpoint()
            editor.insert(" and more")
            editor.selection = Selection((0, 1), (0, 5))
            await pilot.pause()
            expected = editor.text
            history = editor.history
            document = editor.document

            second_mode = (await app.session_navigation.new(app.session_navigation.default_source)).mode_name
            await pilot.pause()
            assert first.query_one(Conversation) is first_surface
            second = app.selected_session
            second_surface = second.conversation
            assert second_surface is not first_surface
            assert first_surface._task is original_task
            assert window in app.workspace_screen.viewport_presentation.windows and window.screen is app.workspace_screen
            second.conversation.prompt.text = "second draft"

            await select(app, pilot, first)
            await pilot.pause()
            restored = first.query_one(PromptTextArea)
            assert first.conversation is first_surface and first_surface._task is original_task
            assert window in app.workspace_screen.viewport_presentation.windows and window.screen is app.workspace_screen
            assert restored.text == expected
            assert restored.document is document and restored.history is history
            assert restored.selection == Selection((0, 1), (0, 5))
            restored.undo()
            assert restored.text == "first draft"
            restored.redo()
            assert restored.text == expected
            assert app.workspace_sessions.require(second_mode).conversation is second_surface
            await select(app, pilot, second)
            assert second.conversation is second_surface
            assert second.conversation.prompt.text == "second draft"
            await second.conversation.post_shell("sleep 1; printf 'owned-shell-marker\\n'")
            async with asyncio.timeout(5):
                while not second.conversation.query("ShellTerminal"):
                    await pilot.pause(.02)
            shell = second.conversation._shell
            assert shell.surface.target is second_surface
            assert len(shell.events.subscriptions) == 1
            shell_operation = shell._operation
            shell_custody = await shell_operation.custody()
            command_view = second_surface.query_one(ShellResult)
            terminal_view = shell.output.terminal
            async with asyncio.timeout(5):
                while not await shell.is_busy():
                    await pilot.pause(.02)
            await second.conversation.submit_input(UserInputSubmitted("busy-shell-input", shell=True))
            # Widget.focus publishes through App.call_later; direct PTY writes
            # no longer happen to await a separate executor first.
            await pilot.pause()
            assert app.focused is shell.output.terminal
            third = (await app.session_navigation.new(app.session_navigation.default_source)).mode_name
            assert second.query_one(Conversation) is second_surface
            assert second.presentation.sources.shell is shell
            assert shell._operation is shell_operation and not shell_operation.task.done()
            assert await shell._operation.custody() is shell_custody
            assert shell_custody.child.alive()
            assert shell.surface.target is None and not shell.events.subscriptions
            async with asyncio.timeout(5):
                while not any("owned-shell-marker" in "\n".join(line.content.plain for line in output.state.buffer.lines)
                              for output in shell.outputs if isinstance(output, ShellTerminalOutput)):
                    await pilot.pause(.02)
            assert all(output.terminal is None for output in shell.outputs
                       if isinstance(output, ShellTerminalOutput))
            await select(app, pilot, second)
            restored_shell_view = app.selected_session.conversation
            assert restored_shell_view is second_surface
            assert restored_shell_view._shell is shell
            assert shell.surface.target is restored_shell_view
            assert len(shell.events.subscriptions) == 1
            assert restored_shell_view.prompt.text == "second draft"
            assert tuple(restored_shell_view.query(ShellResult)) == (command_view,)
            assert any(output is command_view.source for output in shell.outputs)
            assert command_view.get_clipboard_text() == command_view.source.command
            assert terminal_view in restored_shell_view.query("ShellTerminal")
            assert any(output.terminal is terminal_view for output in shell.outputs
                       if isinstance(output, ShellTerminalOutput))
            assert any(terminal.state is output.state for terminal in restored_shell_view.query("ShellTerminal")
                       for output in shell.outputs if isinstance(output, ShellTerminalOutput))
            await pilot.pause()
            paint = conversation_paint(app.screen)
            assert "owned-shell-marker" in paint, paint
            # Read actual terminal pixels, excluding the command caption.
            terminal_paint = "\n".join(
                strip.crop(terminal.region.x, terminal.region.right).text
                for output in shell.outputs if isinstance(output, ShellTerminalOutput)
                for terminal in (output.terminal,) if terminal is not None
                for strip in app.screen._compositor.render_strips()[terminal.region.y:terminal.region.bottom]
            )
            assert "owned-shell-marker" in terminal_paint, terminal_paint
            shell_directory = root / "shell directory"
            shell_directory.mkdir()
            await shell.change_directory(str(shell_directory))
            async with asyncio.timeout(5):
                while restored_shell_view.working_directory != str(shell_directory):
                    await pilot.pause(.02)
            assert shell.working_directory == str(shell_directory)
            if evidence_path := os.environ.get("L0A_EVIDENCE"):
                evidence = Path(evidence_path)
                evidence.mkdir(parents=True, exist_ok=True)
                app.save_screenshot("retained-shell.svg", path=str(evidence))
                (evidence / "shell-publication.json").write_text(json.dumps({
                    "terminal_paint": terminal_paint,
                    "directory_changed_through_original_stream": True,
                    "same_shell_task_process_model": True,
                    "same_command_widget_source": True,
                    "same_terminal_widget_model": True,
                    "active_shell_subscriptions": len(shell.events.subscriptions),
                    "provider_calls": 0,
                }, indent=2) + "\n")
            await select(app, pilot, app.workspace_sessions.require(third))
            assert second.query_one(Conversation) is second_surface
            assert second.presentation.sources.shell is shell
            sidebar = app.selected_session.query_one("#thread-sidebar", SideBar)
            assert not sidebar._panels_loaded
            sidebar.reveal()
            async with asyncio.timeout(5):
                await sidebar.wait_content_ready()
            assert sidebar._panels_loaded and sidebar.query_one("#plan-panel")
            other_project = root / "other-project"
            other_project.mkdir()
            await app.session_navigation.new(lambda: MainScreen(other_project))
            async with asyncio.timeout(5):
                while app.selected_session.conversation._directory_watcher is None:
                    await pilot.pause(.02)
            assert app.selected_session.conversation.project_path == other_project
            assert app.selected_session.conversation._directory_watcher._path == other_project
            await select(app, pilot, app.workspace_sessions.require(third))
            assert app.selected_session.conversation.project_path == root
            assert app.selected_session.conversation._directory_watcher._path == root
            assert app._exception is None
        assert shell_custody.child.retired, "Logical session close leaked its shell process"
        assert shell_operation.task.done(), "Logical session close leaked its reader"
        await asyncio.get_running_loop().shutdown_default_executor()
    print("RETAINED_PHYSICAL_ABA_DRAFT_UNDO_SHELL_OWNER_CLOSE_PASS")


if __name__ == "__main__":
    asyncio.run(main())
