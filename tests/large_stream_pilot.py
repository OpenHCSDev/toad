"""A growing table-heavy answer stays bounded and its final lines remain reachable."""

import asyncio
import os
import tempfile
import time
from pathlib import Path

from textual.geometry import Size

from toad.app import ToadApp
from toad.widgets.agent_response import AgentResponse


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-large-stream-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(70, 25)) as pilot:
            await pilot.pause()
            conversation = app.screen.conversation
            source = "| Name | Purpose | State |\n| --- | --- | --- |\n"
            response = await conversation.post(AgentResponse(source))
            conversation.window.anchor()
            maximum = 0
            for index in range(120):
                part = f"| Item {index} | " + "Descriptive content " * 5 + "| Ready |\n"
                source += part
                await response.append(part)
                maximum = max(maximum, len(list(response.query("*"))))
            source += "\n\nFINAL_END_SENTINEL"
            await response.append("\n\nFINAL_END_SENTINEL")
            await pilot.pause()
            assert response.source == source
            assert maximum < 300, maximum
            for width, height in ((145, 40), (70, 25), (100, 35), (70, 25)):
                await pilot.resize_terminal(width, height)
                conversation.jump_to_latest()
                await pilot.pause()
                frame = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
                assert "FINAL_END_SENTINEL" in frame, (width, frame)
                assert response.virtual_size.height <= response.content_size.height
            # Exercise the asynchronous stream while input and resize events are
            # being handled, rather than inferring responsiveness from idle CPU.
            streaming = asyncio.Event()
            release = asyncio.Event()
            gaps = []

            async def heartbeat():
                previous = time.perf_counter()
                while not release.is_set():
                    await asyncio.sleep(.01)
                    now = time.perf_counter()
                    gaps.append(now - previous)
                    previous = now

            async def stream():
                nonlocal maximum
                index = 0
                while not release.is_set():
                    await response.append_fragment(f"\n\nLive paragraph {index}: " + "content " * 12)
                    streaming.set()
                    maximum = max(maximum, len(list(response.query("*"))))
                    index += 1
                    await asyncio.sleep(.02)
                await response.append_fragment("\n\nSTREAM_END_SENTINEL")
                await response.finish_stream()

            heartbeat_task = asyncio.create_task(heartbeat())
            stream_task = asyncio.create_task(stream())
            resize_times = []
            try:
                await streaming.wait()
                conversation.prompt.focus()
                await pilot.press("d", "r", "a", "f", "t")
                assert conversation.prompt.text == "draft"
                for width, height in ((145, 40), (70, 25), (100, 35)):
                    started = time.perf_counter()
                    resize = asyncio.create_task(pilot.resize_terminal(width, height))
                    # Pilot.pause waits up to a second for *idle*, which a live
                    # stream need never reach. Measure the resized frame instead.
                    try:
                        async with asyncio.timeout(3):
                            while app.screen.size != Size(width, height):
                                await asyncio.sleep(.001)
                            painted = asyncio.Event()
                            app.screen.call_after_refresh(painted.set)
                            await painted.wait()
                        resize_times.append((time.perf_counter() - started) * 1000)
                    finally:
                        await resize
            finally:
                release.set()
                await stream_task
                await heartbeat_task
            conversation.jump_to_latest()
            await pilot.pause()
            frame = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
            assert "STREAM_END_SENTINEL" in frame
            assert maximum < 300, maximum
            assert conversation.prompt.text == "draft"
            print({
                "source_characters": len(response.source),
                "maximum_message_widgets": maximum,
                "streaming_resize_ms": resize_times,
                "streaming_max_loop_gap_ms": max(gaps, default=0) * 1000,
            })


if __name__ == "__main__":
    asyncio.run(main())
