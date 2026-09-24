"""New snapshot metadata must not reflow an unchanged transcript/sidebar tree."""

import asyncio
from dataclasses import replace
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from agent_comms import Thread, wire
from runtime_fixture import ToadApp
from toad.widgets.agent_response import AgentResponse
from toad.widgets.comms_sidebar import ChannelGroup, CommsSidebar


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-metadata-reflow-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        wire(root / "wire").register(Thread("fixture", frozenset({"test"}), str(root), pid=os.getpid()))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            sidebar = app.screen.query_one(CommsSidebar)
            async with asyncio.timeout(5):
                while sidebar._last_snapshot is None:
                    await pilot.pause(.02)
            await app.screen.conversation.contents.mount(*[
                AgentResponse(f"Reply {index}\n\n" + "Paragraph.\n\n" * 16, paginate=False)
                for index in range(100)
            ])
            app.screen.conversation.window.anchor()
            await pilot.pause()
            with patch.object(CommsSidebar, "_refresh"):
                snapshot = sidebar._last_snapshot
                assert snapshot.wire.channels
                screen = app.screen
                with patch.object(screen, "_refresh_layout", wraps=screen._refresh_layout) as layout:
                    for tick in range(5):
                        state = replace(snapshot.wire, channels=tuple(
                            replace(view, last_activity=view.last_activity + tick + 1)
                            for view in snapshot.wire.channels
                        ))
                        await sidebar._present_snapshot(sidebar._snapshot(state))
                        await pilot.pause(.03)
                    assert layout.call_count == 0, f"Metadata-only updates caused {layout.call_count} layouts"

                # A real collapse/expand still reconciles members and geometry.
                group = next(group for group in sidebar.query(ChannelGroup) if group._view.members)
                before = group.expanded
                group.toggle_members()
                await pilot.pause()
                assert group.expanded is not before
                assert bool(group.member_rows) == group.expanded
                group.toggle_members()
                await pilot.pause()
                assert group.expanded is before
            print({"widgets": len(list(screen.walk_children())), "metadata_layouts": 0,
                   "disclosure_still_works": True})
        await asyncio.get_running_loop().shutdown_default_executor()


if __name__ == "__main__":
    asyncio.run(main())
