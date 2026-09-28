"""Applying sidebar intent must not synchronously materialize dirty full geometry."""

import asyncio
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from runtime_fixture import ToadApp
from toad.widgets.side_bar import SideBar


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-sidebar-boundary-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(130, 43)) as pilot:
            await pilot.pause()
            compositor = app.screen._compositor
            for selector in ("#channels-sidebar", "#thread-sidebar"):
                sidebar = app.screen.query_one(selector, SideBar)
                for _ in range(2):
                    compositor._full_map_invalidated = True
                    compositor._visible_map = None
                    with patch.object(compositor, "_arrange_root", wraps=compositor._arrange_root) as arrange:
                        sidebar.toggle(focus=False)
                    assert arrange.call_count == 0, "Sidebar intent performed a synchronous full reflow"
                    await pilot.pause()
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("sidebar intent: consumes committed parent extent; dirty geometry remains deferred to native layout")


if __name__ == "__main__":
    asyncio.run(main())
