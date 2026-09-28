"""A blank tab's editor survives UI retirement without retaining its widget tree."""

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from runtime_fixture import ToadApp
from textual.widgets.text_area import Selection

from toad.widgets.conversation import Conversation
from toad.widgets.prompt import PromptTextArea
from toad.widgets.side_bar import SideBar


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
            assert window in first.body_windows
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
            assert window not in first.body_windows and window in second.body_windows
            assert window not in first.screen_layout_refresh_signal._subscriptions
            assert len(second.screen_layout_refresh_signal._subscriptions[window]) == 2
            second.conversation.prompt.text = "second draft"

            await app.switch_mode(first.id)
            await pilot.pause()
            restored = first.query_one(PromptTextArea)
            assert first.conversation is shared_surface and shared_surface._task is original_task
            assert window in first.body_windows and window not in second.body_windows
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
            await second.conversation.post_shell("printf 'owned-shell-marker\\n'")
            async with asyncio.timeout(5):
                while not second.conversation.query("ShellTerminal"):
                    await pilot.pause(.02)
            third = (await app.new_session_screen(app.get_main_screen)).mode_name
            assert second.conversation is shared_surface
            assert second.conversation._shell is not None
            assert app.screen.conversation is not shared_surface
            await app.switch_mode(second_mode)
            assert app.screen.conversation is shared_surface
            await app.switch_mode(third)
            assert second.conversation is shared_surface and second.conversation.prompt.text == "second draft"
            sidebar = app.screen.query_one("#thread-sidebar", SideBar)
            assert not sidebar._panels_loaded
            sidebar.reveal()
            async with asyncio.timeout(5):
                await sidebar.wait_content_ready()
            assert sidebar._panels_loaded and sidebar.query_one("#plan-panel")
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("blank presentation: one shared editor, original undo/selection/drafts, executing shell promoted")


if __name__ == "__main__":
    asyncio.run(main())
