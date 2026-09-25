"""Clicking an already-open thread never creates a provisional tab."""

import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from agent_comms import Thread, wire
from runtime_fixture import ToadApp

from toad.widgets.irc_message import ThreadLink


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-existing-link-") as directory:
        root = Path(directory)
        wire_root = root / "wire"
        os.environ.update(
            AGENT_COMMS_ROOT=str(wire_root),
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_DATA_HOME=str(root / "data"),
            XDG_STATE_HOME=str(root / "state"),
        )
        comms = wire(wire_root)
        for name in ("owner", "peer"):
            comms.register(Thread(name, frozenset(), str(root), pid=os.getpid()))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(100, 36)) as pilot:
            await pilot.pause()
            owner = app.current_mode
            source = app.screen
            source._coordination_root = str(wire_root)
            source._comms_thread = "owner"
            foreign = (await app.new_session_screen(app.get_main_screen)).mode_name
            app.screen._coordination_root = str(root / "foreign-wire")
            app.screen._comms_thread = "peer"
            existing = (await app.new_session_screen(app.get_main_screen)).mode_name
            destination = app.screen
            destination._coordination_root = str(wire_root)
            destination._comms_thread = "peer"
            destination.conversation.prompt.text = "Keep this draft"
            await app.switch_mode(owner)
            link = ThreadLink("peer")
            await source.conversation.contents.mount(link)
            await pilot.pause()
            order = tuple(app._open_tab_order)
            pending_index = app._pending_thread_index
            with (
                patch.object(app, "add_mode", wraps=app.add_mode) as added,
                patch.object(app.navigation_reader, "read", wraps=app.navigation_reader.read) as reads,
            ):
                assert await pilot.click(link)
                await pilot.pause()
                async with asyncio.timeout(3):
                    while app.current_mode != existing:
                        await pilot.pause(.05)
                assert app.screen is destination and app.current_mode != foreign
                assert added.call_count == 0, "Existing link created a transient tab"
                assert reads.call_count == 0, "Existing mounted identity needed route discovery"
                assert app._pending_thread_index == pending_index
                assert tuple(app._open_tab_order) == order
                assert destination.conversation.prompt.text == "Keep this draft"
                assert not app._pending_thread_modes
                # Repeated/self links reuse the very same mounted screen too.
                for _ in range(2):
                    assert await app.open_thread_session(
                        owner_mode=existing, project_path=root, target="peer",
                    ) == existing
                assert added.call_count == 0 and reads.call_count == 0
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("existing thread link: direct focus, no transient tab/IO, root isolation and draft preserved")


if __name__ == "__main__":
    asyncio.run(main())
