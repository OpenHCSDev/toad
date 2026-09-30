"""New snapshot metadata must not reflow an unchanged transcript/sidebar tree."""

import asyncio
from dataclasses import replace
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from agent_comms.child_process import ProcessIdentity
from agent_comms.threads import Thread
from agent_comms.comms import wire
from runtime_fixture import ToadApp
from toad.widgets.agent_response import AgentResponse
from toad.widgets.comms_sidebar import ChannelGroup, CommsSidebar


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-metadata-reflow-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        wire(root / "wire").registry.declare(Thread("fixture", frozenset({"test"}), str(root), process_identity=ProcessIdentity.capture(os.getpid())))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            sidebar = app.screen.query_one(CommsSidebar)
            async with asyncio.timeout(5):
                while sidebar.projection.snapshot is None:
                    await pilot.pause(.02)
            await app.selected_session.conversation.contents.mount(*[
                AgentResponse(f"Reply {index}\n\n" + "Paragraph.\n\n" * 16, paginate=False)
                for index in range(100)
            ])
            app.selected_session.conversation.window.anchor()
            await pilot.pause()
            with patch.object(type(sidebar.observation), "refresh"):
                snapshot = sidebar.projection.snapshot
                assert snapshot.wire.channels
                screen = app.screen
                with patch.object(screen, "_refresh_layout", wraps=screen._refresh_layout) as layout:
                    for tick in range(5):
                        state = replace(snapshot.wire, channels=tuple(
                            replace(view, last_activity=view.last_activity + tick + 1)
                            for view in snapshot.wire.channels
                        ))
                        await sidebar.projection.publish(sidebar.observation.project(state))
                        await pilot.pause(.03)
                    assert layout.call_count == 0, f"Metadata-only updates caused {layout.call_count} layouts"

                # A real collapse/expand still reconciles members and geometry.
                group = next(group for group in sidebar.query(ChannelGroup) if group._view.members)
                before = group.expanded
                group.toggle_members()
                await pilot.pause()
                assert group.expanded is not before
                assert bool(group.member_container.children) == group.expanded
                group.toggle_members()
                await pilot.pause()
                assert group.expanded is before

                # Hold the actual native removal after it completes, before
                # reconciliation returns. Navigation must not retain retired
                # rows while the group's serialized update is still pending.
                if not group.expanded:
                    group.toggle_members()
                    await pilot.pause()
                retired = tuple(group.member_container.children)
                assert retired
                removed, release = asyncio.Event(), asyncio.Event()
                remove_children = group.member_container.remove_children

                async def held_remove(*args, **kwargs):
                    await remove_children(*args, **kwargs)
                    removed.set()
                    await release.wait()

                with patch.object(group.member_container, "remove_children", held_remove):
                    click = asyncio.create_task(pilot.click(group.disclosure))
                    try:
                        async with asyncio.timeout(5):
                            await removed.wait()
                        assert not group.member_container.children
                        assert not any(row in sidebar.projection.rows for row in retired)
                        assert not any(row in sidebar.projection.thread_rows for row in retired)
                        assert not any(row.is_attached for row in retired)
                    finally:
                        release.set()
                        await click
                await pilot.pause()
                assert await pilot.click(group.disclosure)
                await pilot.pause()
                assert tuple(group.member_container.children)
                assert all(row in sidebar.projection.thread_rows
                           for row in group.member_container.children)
                with patch.object(sidebar, "query", wraps=sidebar.query) as query:
                    sidebar.navigation.mode_changed(app.selected_mode, force=True)
                    assert query.call_count == 0
                assert all(row.current == (row.mode_name == app.selected_mode)
                           for row in sidebar.projection.thread_rows)
            print({"widgets": len(list(screen.walk_children())), "metadata_layouts": 0,
                   "disclosure_still_works": True, "retired_navigation_rows": 0})
        await asyncio.get_running_loop().shutdown_default_executor()


if __name__ == "__main__":
    asyncio.run(main())
