"""Measure composer dispatch latency and verify queued typing is not lost."""

import asyncio
import json
import os
import statistics
import tempfile
import time
from pathlib import Path

from toad.app import ToadApp
from toad.messages import UserInputSubmitted


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-input-latency-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            area = app.screen.conversation.prompt.prompt_text_area
            area.focus()
            await pilot.pause()
            original = area.post_message
            dispatched = asyncio.Event()
            submitted: list[str] = []
            timings: list[float] = []
            started = 0.0

            def capture(message):
                if isinstance(message, UserInputSubmitted):
                    submitted.append(message.body)
                    timings.append(time.perf_counter() - started)
                    dispatched.set()
                    return True
                return original(message)

            area.post_message = capture
            for index in range(20):
                area.text = f"message {index}"
                dispatched.clear()
                started = time.perf_counter()
                area.action_submit()
                await asyncio.wait_for(dispatched.wait(), 2)
            assert submitted == [f"message {index}" for index in range(20)]
            print(json.dumps({"median_submit_ms": 1000 * statistics.median(timings),
                              "max_submit_ms": 1000 * max(timings)}, indent=2))
            await pilot.press("f", "a", "s", "t", "enter")
            await pilot.pause()
            assert submitted[-1] == "fast"


if __name__ == "__main__":
    asyncio.run(main())
