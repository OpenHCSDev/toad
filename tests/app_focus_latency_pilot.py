"""Interleaved focus-event comparison on one mounted long Toad transcript."""

import asyncio
from contextlib import nullcontext
import os
from pathlib import Path
import statistics
import tempfile
import time
from unittest.mock import patch

from runtime_fixture import ToadApp
from toad.widgets.agent_response import AgentResponse


class FocusProbe(ToadApp):
    pending = None

    def _display(self, screen, renderable):
        result = super()._display(screen, renderable)
        if (self.pending is not None and not self.pending.done()
                and renderable is not None and not self._batch_count
                and screen is self.screen):
            self.pending.set_result(time.perf_counter())
        return result


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-focus-frame-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"),
                          XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"))
        app = FocusProbe(project_dir=str(root))
        results = {"whole_screen": [], "dependency_filtered": []}
        synchronous = {name: [] for name in results}
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await app.screen.conversation.contents.mount(*[
                AgentResponse(f"## Response {index}\n\n" + "A paragraph with **bold** and `code`.\n\n" * 8,
                              paginate=False) for index in range(45)
            ])
            await pilot.pause()
            focused_widget = app.screen.focused
            for _ in range(4):
                for name in results:
                    context = (patch.object(app.stylesheet, "update_app_focus",
                                lambda screen: app.stylesheet.update(screen, animate=True))
                               if name == "whole_screen" else nullcontext())
                    with context:
                        for focused in (False, True):
                            await pilot.pause()
                            app.pending = asyncio.get_running_loop().create_future()
                            started = time.perf_counter()
                            app.app_focus = focused
                            synchronous[name].append((time.perf_counter() - started) * 1000)
                            finished = await asyncio.wait_for(app.pending, 5)
                            results[name].append((finished - started) * 1000)
                            app.pending = None
                        await pilot.pause()
                        assert app.screen.focused is focused_widget
            print({"widgets": len(list(app.screen.walk_children())),
                   "boundary": "headless post-_display, not terminal presentation",
                   "focus_transitions": {
                       name: {"median_ms": round(statistics.median(samples), 2),
                              "worst_ms": round(max(samples), 2),
                              "synchronous_median_ms": round(statistics.median(synchronous[name]), 2)}
                       for name, samples in results.items()}})
        await asyncio.get_running_loop().shutdown_default_executor()


if __name__ == "__main__":
    asyncio.run(main())
