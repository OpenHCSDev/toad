"""Textual-facing: a hidden session's tree and watcher hold filesystem changes until the session is shown again."""

import asyncio

from watchdog.events import FileCreatedEvent

from support.textual_steps import reveal_project_tree


async def test_hidden_tab_emits_no_ui_events_and_resuming_flushes_one_pending_change(workspace):
    async with workspace.app(size=(110, 40)) as ui:
        app, _ = ui.textual
        original = ui.selected_tab
        tree = await reveal_project_tree(ui)
        watcher = ui.conversation._directory_watcher
        assert watcher is not None
        await ui.new_session()
        for index in range(100):
            watcher.on_any_event(FileCreatedEvent(str(workspace.project / f"result-{index}.txt")))
        await ui.step()
        assert watcher._dirty
        assert not tree._directory_dirty
        assert not tree._refresh_scheduled
        await ui.select_tab(original)
        await ui.until(lambda: not (watcher._dirty or tree._directory_dirty or tree._refresh_scheduled),
                       seconds=5, why="the pending change flushed")
