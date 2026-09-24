"""Thread and channel tabs share one opening order across every screen."""

import asyncio
import os
import tempfile
from pathlib import Path

from agent_comms import Thread, wire
from runtime_fixture import ToadApp
from toad.widgets.session_tabs import SessionsTabs, SessionLabel


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-tab-order-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        comms = wire(root / "wire")
        comms.register(Thread("owner", frozenset(), str(root)))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(140, 32)) as pilot:
            await pilot.pause()
            first = app.current_mode
            channel = await app.open_comms_session(owner_mode=first, project_path=root,
                me="owner", target="#all", kind="channel")
            second = (await app.new_session_screen(app.get_main_screen)).mode_name
            expected = [first, channel, second]
            for mode in expected * 2:
                await app.switch_mode(mode)
                await pilot.pause()
                assert [tab.mode_name for tab in app.open_tabs] == expected
                assert [label.id for label in app.screen.query_one(SessionsTabs).query(SessionLabel)] == expected
            await app.close_session_mode(channel)
            expected.remove(channel)
            for mode in expected:
                await app.switch_mode(mode)
                await pilot.pause()
                assert [label.id for label in app.screen.query_one(SessionsTabs).query(SessionLabel)] == expected
    print("tab order: interleaved channel/thread opening order survives all selections and closure")


if __name__ == "__main__":
    asyncio.run(main())
