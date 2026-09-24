"""Hidden sessions defer filesystem invalidation until their first active frame."""

import asyncio
import os
import tempfile
from pathlib import Path

from watchdog.events import FileCreatedEvent

from runtime_fixture import ToadApp, reveal_project_tree
from toad.screens.main import MainScreen


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-watcher-hidden-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(110, 40)) as pilot:
            await pilot.pause()
            original = app.current_mode
            old_screen = app.screen
            tree = await reveal_project_tree(app, pilot)
            watcher = old_screen.conversation._directory_watcher
            assert watcher is not None
            await app.new_session_screen(lambda: MainScreen(root))
            await pilot.pause()
            for index in range(100):
                watcher.on_any_event(FileCreatedEvent(str(root / f"result-{index}.txt")))
            await pilot.pause()
            assert watcher._dirty
            assert not tree._directory_dirty
            assert not tree._refresh_scheduled
            await app.switch_mode(original)
            async with asyncio.timeout(5):
                while watcher._dirty or tree._directory_dirty or tree._refresh_scheduled:
                    await pilot.pause(.02)
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("watcher visibility: hidden tabs emit no UI events; resume flushes one pending change")


if __name__ == "__main__":
    asyncio.run(main())
