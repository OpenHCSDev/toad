"""Warm tab switches retain native channel rows and never paint an empty roster."""

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from agent_comms.comms import wire
from agent_comms.threads import Thread

from runtime_fixture import ToadApp
from toad.widgets.comms_chat import session_thread_name
from toad.widgets.comms_sidebar import CommsSidebar
from toad.widgets.side_bar import SideBar


class FrameApp(ToadApp):
    expected_modes = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.roster_frames = []

    def _display(self, screen, renderable):
        super()._display(screen, renderable)
        if (self.expected_modes is not None and self.current_mode in self.expected_modes
                and screen is self.screen and renderable is not None and not self._batch_count):
            sidebar = screen.query_one_optional(CommsSidebar)
            visible = screen._compositor.visible_widgets
            self.roster_frames.append((self.current_mode, sidebar is not None and any(
                item.target_name == "#all" and item in visible
                for item in sidebar._row_map.values()
            )))


async def settled(app, pilot):
    async with asyncio.timeout(12):
        while True:
            await pilot.pause(.02)
            sidebar = app.screen.query_one_optional(CommsSidebar)
            if (sidebar is not None and sidebar.display and sidebar.navigation_ready.is_set()
                    and sidebar._last_snapshot is not None and not sidebar._snapshot_pending
                    and any(item.target_name == "#kept" for item in sidebar._row_map.values())):
                return sidebar


async def main():
    with TemporaryDirectory(prefix="toad-channel-roster-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        comms = wire(root / "wire")
        me = session_thread_name(root)
        comms.threads.register(Thread(me, frozenset({"fixture"}), str(root), pid=os.getpid()))
        comms.channels.set_channel("#kept", frozenset({"fixture"}))
        comms.messaging.send(me, "#kept", "Retained source")
        app = FrameApp(project_dir=str(root))
        async with app.run_test(size=(130, 45)) as pilot:
            first = app.current_mode
            await settled(app, pilot)
            second = (await app.new_session_screen(app.get_main_screen)).mode_name
            await settled(app, pilot)
            channel = await app.open_comms_session(owner_mode=first, project_path=root,
                                                   me=me, target="#kept", kind="channel")
            await settled(app, pilot)
            modes = (first, second, channel)
            sidebars, original_rows = {}, {}
            for mode in modes:
                await app.switch_mode(mode)
                sidebar = await settled(app, pilot)
                app.screen.query_one("#channels-sidebar", SideBar).reveal()
                await pilot.pause()
                sidebars[mode] = sidebar
                original_rows[mode] = dict(sidebar._row_map)

            # Visiting other tabs must not destroy an already rendered roster.
            for mode in modes:
                assert all(item.is_attached and not item._closed
                           for item in original_rows[mode].values()), (
                    "Warm channel rows retired on tab switch", mode)
            for mode in modes[:-1]:
                sidebar = sidebars[mode]
                with patch.object(sidebar, "_route_stamp", wraps=sidebar._route_stamp) as probe:
                    sidebar._refresh()
                    assert not probe.called, "An inactive retained roster still polls its source"

            app.expected_modes = set(modes)
            for mode in (*reversed(modes), *modes, *reversed(modes)):
                await app.switch_mode(mode)
                sidebar = await settled(app, pilot)
                assert sidebar._row_map == original_rows[mode]
            assert app.roster_frames and all(present for _, present in app.roster_frames), app.roster_frames
            app.expected_modes = None

            # Real wire changes still reconcile, preserving unaffected row identities.
            retained = dict(sidebars[second]._row_map)
            comms.channels.set_channel("#added", frozenset({"fixture"}))
            active = app.screen.query_one(CommsSidebar)
            active._refresh()
            async with asyncio.timeout(12):
                while not any(item.target_name == "#added" for item in active._row_map.values()):
                    await pilot.pause(.02)
            await app.switch_mode(second)
            sidebar = await settled(app, pilot)
            async with asyncio.timeout(12):
                while not any(item.target_name == "#added" for item in sidebar._row_map.values()):
                    await pilot.pause(.02)
            assert all(sidebar._row_map[key] is item for key, item in retained.items())

            # Retention is not route authority. A route change hides old rows
            # synchronously; the normal validated refresh can show them again.
            stamp = sidebar._route_stamp()
            with patch.object(sidebar, "_route_stamp", return_value=((0, 1, 2, 3), stamp[1])):
                sidebar.prepare_navigation()
                assert not sidebar.display
                assert all(item.is_attached for item in retained.values())
            sidebar._refresh()
            await settled(app, pilot)

            await app.switch_mode(first)
            await settled(app, pilot)
            closed_rows = tuple(sidebars[second]._row_map.values())
            await app.close_session_mode(second)
            await pilot.pause()
            assert closed_rows and all(item._closed and not item.is_attached for item in closed_rows)
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("channel roster: retained identities and every warm frame; real updates and close cleanup pass")


if __name__ == "__main__":
    asyncio.run(main())
