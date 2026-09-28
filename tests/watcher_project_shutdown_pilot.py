"""Mount the installed UI on a real project and close while the native watcher starts."""

import asyncio
import json
import os
import tempfile
from pathlib import Path

import psutil

from toad.app import ToadApp


async def main():
    with tempfile.TemporaryDirectory(prefix="watcher-project-ui-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"),
                          XDG_CONFIG_HOME=str(root / "config"),
                          XDG_DATA_HOME=str(root / "data"),
                          XDG_STATE_HOME=str(root / "state"))
        project = Path(os.environ["WATCHER_ACTUAL_PROJECT"])
        app = ToadApp(project_dir=str(project))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            view = app.screen.conversation
            view.watch_agent_ready(True)
            watcher = view._directory_watcher
            view.watch_agent_ready(True)
            assert view._directory_watcher is watcher
            async with asyncio.timeout(8):
                while (watcher._observation is None
                       or watcher._observation.process.pid is None):
                    await pilot.pause(.01)
            pid = watcher._observation.process.pid
            await pilot.pause(.1)
            ready_at_close = watcher.enabled
        await asyncio.to_thread(watcher.join, 3)
        assert not watcher.is_alive() and not psutil.pid_exists(pid)
        assert app._exception is None
        print(json.dumps({"project": str(project), "native_ready_at_close": ready_at_close,
                          "watcher_reused": True, "watcher_and_child_joined": True}), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
    print("PASS: actual project UI and interpreter shutdown completed", flush=True)
