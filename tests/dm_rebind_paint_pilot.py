"""A mounted DM view cannot acknowledge a replacement peer it never painted."""

import asyncio
import os
import tempfile
from pathlib import Path
from threading import Event
from unittest.mock import patch

from agent_comms import Comms, Thread, wire
from runtime_fixture import ToadApp
from toad.widgets.comms_chat import CommsChatView


async def until(pilot, condition):
    async with asyncio.timeout(8):
        while not condition():
            await pilot.pause(0.02)


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-dm-rebind-") as directory:
        root = Path(directory)
        os.environ.update(
            AGENT_COMMS_ROOT=str(root / "wire"),
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_STATE_HOME=str(root / "state"),
            XDG_DATA_HOME=str(root / "data"),
        )
        comms = wire(root / "wire")
        comms.register(Thread("peer", frozenset(), str(root), pid=os.getpid()))
        viewer = comms.user_identity(str(root)).name
        comms.send("peer", viewer, "old peer painted")
        entered, release = Event(), Event()
        original_mark = Comms.mark_dm_view_read

        def pause_old_mark(self, peer, **kwargs):
            entered.set()
            if not release.wait(8):
                raise TimeoutError("Old painted marker was not released")
            return original_mark(self, peer, **kwargs)

        app = ToadApp(project_dir=str(root))
        try:
            with patch.object(Comms, "mark_dm_view_read", pause_old_mark):
                async with app.run_test(size=(120, 40)) as pilot:
                    await pilot.pause()
                    owner_mode = app.current_mode
                    await app.open_comms_session(
                        owner_mode=owner_mode,
                        project_path=root,
                        me=viewer,
                        target="peer",
                        kind="dm",
                    )
                    chat = app.screen.query_one(CommsChatView)
                    assert await asyncio.to_thread(entered.wait, 4)
                    assert [message.body for message, _ in chat._history] == [
                        "old peer painted"
                    ]
                    assert comms.pending_count(viewer, "peer") == 1

                    comms.registry.unregister("peer")
                    comms.delete("peer")
                    comms.register(
                        Thread("peer", frozenset(), str(root), pid=os.getpid())
                    )
                    comms.send("peer", viewer, "new peer never painted")
                    await app.switch_mode(owner_mode)
                    release.set()
                    await until(pilot, lambda: not chat._ack_inflight)
                    assert comms.pending_count(viewer, "peer") == 1
                    assert not any(
                        message.body == "new peer never painted"
                        for message, _ in chat._history
                    )
                    assert app._exception is None
        finally:
            release.set()
        await asyncio.get_running_loop().shutdown_default_executor()
    print(
        "DM rebind: an old painted page did not acknowledge a hidden replacement peer"
    )


if __name__ == "__main__":
    asyncio.run(main())
