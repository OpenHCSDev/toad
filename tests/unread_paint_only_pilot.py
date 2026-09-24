"""Same-width unread changes repaint badges/tabs without relaying out history."""

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
from toad.widgets.session_tabs import SessionLabel


async def main():
    with tempfile.TemporaryDirectory(prefix="unread-paint-only-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        comms = wire(root / "wire")
        comms.register(Thread("fixture", frozenset({"test"}), str(root), pid=os.getpid()))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            first = app.current_mode
            screen = app.screen
            screen.on_comms_session_named("fixture")
            await app.new_session_screen(app.get_main_screen)
            await app.switch_mode(first)
            await screen.conversation.contents.mount(*[
                AgentResponse(f"Reply {index}\n\n" + "Paragraph under unread updates.\n\n" * 12,
                              paginate=False)
                for index in range(40)
            ])
            screen.conversation.window.anchor()
            await pilot.pause()
            sidebar = screen.query_one(CommsSidebar)
            for timer in tuple(sidebar._timers):
                timer.pause()
            await sidebar.sync_sessions()
            await pilot.pause()
            with patch.object(CommsSidebar, "_refresh"):
                snapshot = sidebar._last_snapshot
                assert snapshot is not None
                group = next(group for group in sidebar.query(ChannelGroup)
                             if group.row.target_name == "#test")

                async def channel_count(count):
                    state = replace(snapshot.wire, channel_unread={**snapshot.wire.channel_unread, "#test": count})
                    await sidebar._present_snapshot(sidebar._snapshot(state))
                    await pilot.pause(.02)
                    assert group.unread_badge.render().plain == f"({count})"
                    assert group.unread_badge.display == bool(count)

                await channel_count(10)
                with patch.object(screen, "_refresh_layout", wraps=screen._refresh_layout) as layout:
                    for count in (11, 12, 19):
                        await channel_count(count)
                    print({"same_width_channel_badge_layouts": layout.call_count})
                    assert layout.call_count == 0
                    await channel_count(100)
                    assert layout.call_count > 0
                    for count in (0, 9, 10):
                        layout.reset_mock()
                        await channel_count(count)
                        assert layout.call_count > 0

                async def thread_count(count):
                    state = replace(snapshot.wire, thread_unread={**snapshot.wire.thread_unread, "fixture": count})
                    app._sidebar_snapshot = state
                    await sidebar._present_snapshot(sidebar._snapshot(state))
                    await pilot.pause(.02)
                    text = screen.query_one(f"SessionLabel#{first}", SessionLabel).render().plain
                    assert (f"({count})" in text) if count else ("(" not in text)

                await thread_count(10)
                with patch.object(screen, "_refresh_layout", wraps=screen._refresh_layout) as layout:
                    for count in (11, 12, 19):
                        await thread_count(count)
                    print({"same_width_tab_unread_layouts": layout.call_count})
                    assert layout.call_count == 0
                    await thread_count(100)
                    assert layout.call_count > 0
                    for count in (0, 9, 10):
                        layout.reset_mock()
                        await thread_count(count)
                        assert layout.call_count > 0
                assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()


if __name__ == "__main__":
    asyncio.run(main())
