"""Polling revisions must not lay out an unchanged conversation/right panel."""

import asyncio
from dataclasses import replace
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from agent_comms import ThreadSort
from textual.widgets import TextArea
from right_comms_pilot import FixtureSource
from runtime_fixture import ToadApp
from toad.widgets.agent_response import AgentResponse
from toad.widgets.side_bar import SideBar, SideBarCollapsible
from toad.widgets.thread_comms import RelationshipSort, ThreadCommsSidebar


async def main():
    with tempfile.TemporaryDirectory(prefix="relationship-poll-reflow-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        source = FixtureSource(root / "wire")
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(130, 44)) as pilot:
            await pilot.pause()
            screen = app.screen
            await screen.conversation.contents.mount(*[
                AgentResponse(f"Reply {index}\n\n" + "Paragraph under the polling panel.\n\n" * 12,
                              paginate=False)
                for index in range(40)
            ])
            screen.conversation.window.anchor()
            right = screen.query_one("#thread-sidebar", SideBar)
            right.reveal()
            previous_tree = right.query_one(ThreadCommsSidebar)
            panel = previous_tree.query_ancestor(SideBarCollapsible)
            container = previous_tree.parent
            assert container is not None
            await previous_tree.remove()
            tree = ThreadCommsSidebar("owner", wire_root=str(root / "wire"), source=source)
            await container.mount(tree)
            panel.collapsed = False
            await pilot.pause()
            for signal in (app.coordination_observed, app.open_tabs_changed,
                           app.mode_change_signal, app.thread_actions_changed):
                signal.unsubscribe(tree)
            # Use the production async read/apply path with a typed test source.
            # Suppress only external observation delivery while advancing it by
            # explicit source revisions, so each measured poll is deterministic.
            if tree._refresh_task is not None:
                await tree._refresh_task
            await tree._refresh(tree._generation)
            async with asyncio.timeout(5):
                while not tree.groups or tree._refresh_task is not None and not tree._refresh_task.done():
                    await pilot.pause(.01)
            await pilot.pause()
            for area in screen.query(TextArea):
                area.cursor_blink = False
            await pilot.pause()
            sort = right.query_one(RelationshipSort)
            row = tree.groups["collaborating"].rows["thread", "peer"]
            original_row = row
            with (patch.object(screen, "_refresh_layout", wraps=screen._refresh_layout) as layout,
                  patch.object(app, "_display", wraps=app._display) as display):
                for _ in range(8):
                    source.version += 1
                    await tree._refresh(tree._generation)
                    await pilot.pause(.03)
                layouts, paints = layout.call_count, display.call_count
            print({"unchanged_poll_layouts": layouts, "unchanged_poll_paints": paints,
                   "widgets": len(list(screen.walk_children()))})
            assert layouts == 0, f"Eight unchanged polls caused {layouts} full layouts"
            assert paints == 0, f"Eight unchanged polls caused {paints} redundant paints"
            assert tree.groups["collaborating"].rows["thread", "peer"] is original_row

            # New same-width activity metadata still updates the retained row
            # and tooltip, without turning it into a geometry change.
            person = source.people["peer"]
            source.people["peer"] = replace(person, activity=replace(person.activity, detail="Updated task status"))
            source.version += 1
            with patch.object(screen, "_refresh_layout", wraps=screen._refresh_layout) as layout:
                await tree._refresh(tree._generation)
                await pilot.pause()
                assert "Updated task status" in row.render().plain
                assert layout.call_count == 0

            # A real sort-label width change remains a layout change, and a
            # subsequent unchanged poll does not repeat it.
            source.order = {name: ThreadSort.CREATED for name in source.order}
            source.version += 1
            with patch.object(screen, "_refresh_layout", wraps=screen._refresh_layout) as layout:
                await tree._refresh(tree._generation)
                await pilot.pause()
                assert sort.render().plain == f"{ThreadSort.CREATED.label} ▾"
                assert layout.call_count > 0
                layout.reset_mock()
                source.version += 1
                await tree._refresh(tree._generation)
                await pilot.pause()
                assert layout.call_count == 0
            tree.set_identity("", None)
            await pilot.pause()
            with patch.object(app, "_display", wraps=app._display) as display:
                for _ in range(8):
                    tree._observed(None)
                    await pilot.pause(.02)
                assert display.call_count == 0, "Unchanged waiting state repainted on observation"
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()


if __name__ == "__main__":
    asyncio.run(main())
