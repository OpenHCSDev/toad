"""A blank tab's editor survives UI retirement without retaining its widget tree."""

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from runtime_fixture import ToadApp
from native_session_retention_pilot import conversation_paint
from textual.widgets.text_area import Selection

from toad.widgets.conversation import Conversation
from toad.widgets.prompt import PromptTextArea
from toad.widgets.side_bar import SideBar
from toad.screens.main import MainScreen
from toad.shell_output import ShellTerminalOutput


async def main():
    with TemporaryDirectory(prefix="toad-session-surface-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(100, 35)) as pilot:
            await pilot.pause()
            first = app.screen
            shared_surface = first.conversation
            original_task = shared_surface._task
            window = shared_surface.window
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

            second_mode = (await app.new_session_screen(app.get_main_screen)).mode_name
            await pilot.pause()
            async with asyncio.timeout(5):
                while first.query(Conversation):
                    await pilot.pause(.02)
            assert not first.query(Conversation), "Inactive blank tab retained its entire rich conversation"
            assert first.presentation.editor_state.document is document
            assert first.presentation.editor_state.history is history
            second = app.screen
            assert second.conversation is shared_surface
            assert shared_surface._task is original_task
            assert window not in first.viewport_presentation.windows and window in second.viewport_presentation.windows
            assert window not in first.screen_layout_refresh_signal._subscriptions
            assert len(second.screen_layout_refresh_signal._subscriptions[window]) == 2
            second.conversation.prompt.text = "second draft"

            await app.switch_mode(first.id)
            await pilot.pause()
            restored = first.query_one(PromptTextArea)
            assert first.conversation is shared_surface and shared_surface._task is original_task
            assert window in first.viewport_presentation.windows and window not in second.viewport_presentation.windows
            assert restored.text == expected
            assert restored.document is document and restored.history is history
            assert restored.selection == Selection((0, 1), (0, 5))
            restored.undo()
            assert restored.text == "first draft"
            restored.redo()
            assert restored.text == expected
            assert app.get_screen_stack(second_mode)[0].presentation.editor_state is not None
            await app.switch_mode(second_mode)
            assert second.conversation is shared_surface
            assert second.conversation.prompt.text == "second draft"
            await second.conversation.post_shell("sleep 1; printf 'owned-shell-marker\\n'")
            async with asyncio.timeout(5):
                while not second.conversation.query("ShellTerminal"):
                    await pilot.pause(.02)
            shell = second.conversation._shell
            shell_task, shell_process = shell._task, shell._process
            third = (await app.new_session_screen(app.get_main_screen)).mode_name
            assert not second.query(Conversation)
            assert second.presentation.sources.shell is shell
            assert shell._task is shell_task and not shell_task.done()
            assert shell._process is shell_process and shell_process.returncode is None
            async with asyncio.timeout(5):
                while not any("owned-shell-marker" in "\n".join(line.content.plain for line in output.state.buffer.lines)
                              for output in shell.outputs if isinstance(output, ShellTerminalOutput)):
                    await pilot.pause(.02)
            assert all(output.terminal is None for output in shell.outputs
                       if isinstance(output, ShellTerminalOutput))
            await app.switch_mode(second_mode)
            restored_shell_view = app.screen.conversation
            assert restored_shell_view is not shared_surface
            assert restored_shell_view._shell is shell
            assert restored_shell_view.prompt.text == "second draft"
            assert any(terminal.state is output.state for terminal in restored_shell_view.query("ShellTerminal")
                       for output in shell.outputs if isinstance(output, ShellTerminalOutput))
            await pilot.pause()
            paint = conversation_paint(app.screen)
            assert "owned-shell-marker" in paint, paint
            await app.switch_mode(third)
            assert not second.query(Conversation)
            assert second.presentation.sources.shell is shell
            sidebar = app.screen.query_one("#thread-sidebar", SideBar)
            assert not sidebar._panels_loaded
            sidebar.reveal()
            async with asyncio.timeout(5):
                await sidebar.wait_content_ready()
            assert sidebar._panels_loaded and sidebar.query_one("#plan-panel")
            other_project = root / "other-project"
            other_project.mkdir()
            await app.new_session_screen(lambda: MainScreen(other_project))
            async with asyncio.timeout(5):
                while app.screen.conversation._directory_watcher is None:
                    await pilot.pause(.02)
            assert app.screen.conversation.project_path == other_project
            assert app.screen.conversation._directory_watcher._path == other_project
            await app.switch_mode(third)
            assert app.screen.conversation.project_path == root
            assert app.screen.conversation._directory_watcher._path == root
            assert app._exception is None
        assert shell._process.returncode is not None, "Logical session close leaked its shell process"
        assert shell._task.done(), "Logical session close leaked its reader"
        await asyncio.get_running_loop().shutdown_default_executor()
    print("blank presentation: one shared editor, original undo/selection/drafts, executing shell promoted")


if __name__ == "__main__":
    asyncio.run(main())
