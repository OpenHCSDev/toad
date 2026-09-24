"""A busy project does not enqueue thousands of UI events across hidden tabs."""

import asyncio
import json
import os
import tempfile
import time
from pathlib import Path

from watchdog.events import FileCreatedEvent

from runtime_fixture import ToadApp
from toad.directory_watcher import _shared_observer_manager
from toad.widgets.agent_response import AgentResponse


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-watch-busy-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            modes = [app.current_mode]
            for _ in range(13):
                await app.new_session_screen(app.get_main_screen)
                modes.append(app.current_mode)
            await pilot.pause()
            dispatcher = _shared_observer_manager._observers[root.resolve()][1]
            assert len(dispatcher._watchers) == len(modes)
            await app.screen.conversation.post(AgentResponse("\n\n".join(
                f"Visible paragraph {index}: " + "text " * 20 for index in range(30))))
            await pilot.pause()
            ticks = []

            async def heartbeat():
                previous = time.perf_counter()
                while True:
                    await asyncio.sleep(.01)
                    current = time.perf_counter()
                    ticks.append((current - previous) * 1000)
                    previous = current

            pulse = asyncio.create_task(heartbeat())
            try:
                started = time.perf_counter()
                for index in range(1000):
                    dispatcher.on_any_event(FileCreatedEvent(str(root / f"change-{index}")))
                scheduling_ms = (time.perf_counter() - started) * 1000
                await asyncio.sleep(dispatcher.QUIET_INTERVAL + .1)
                await pilot.pause()
                watchers = list(dispatcher._watchers)
                active = [item for item in watchers if item._widget.screen is app.screen]
                hidden = [item for item in watchers if item._widget.screen is not app.screen]
                assert len(active) == 1 and len(hidden) == 13
                assert all(item._dirty for item in hidden)
                assert not active[0]._dirty
                burst_gap = max(ticks, default=0)
                ticks.clear()
                await app.switch_mode(modes[0])
                await pilot.pause()
                assert not next(item for item in watchers if item._widget.screen is app.screen)._dirty
                print(json.dumps({"tabs": len(modes), "watchers": len(watchers),
                                  "fs_events": 1000, "event_dispatch_ms": round(scheduling_ms, 2),
                                  "burst_loop_gap_ms": round(burst_gap, 1),
                                  "switch_loop_gap_ms": round(max(ticks, default=0), 1)}))
                assert app._exception is None
            finally:
                pulse.cancel()
                await asyncio.gather(pulse, return_exceptions=True)
        await asyncio.get_running_loop().shutdown_default_executor()


if __name__ == "__main__":
    asyncio.run(main())
