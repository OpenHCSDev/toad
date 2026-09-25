"""Observe post-spinner replay and quiet/updated tab returns without a provider."""

import argparse
import asyncio
import cProfile
import json
import os
from pathlib import Path
import tempfile
import time
import sys
from contextlib import ExitStack
from unittest.mock import patch

from agent_comms import Thread, TranscriptCursor, TranscriptEvent, TranscriptPage, wire
from runtime_fixture import ToadApp
from toad.acp.agent import Agent
from toad.acp.messages import TranscriptSnapshot
from toad.agent import AgentReady
from toad.widgets.agent_response import AgentResponse
from toad.widgets.conversation import ThreadLoading
from toad.widgets.footer import Footer
from textual.widget import Widget


async def until(condition):
    async with asyncio.timeout(20):
        while not condition():
            await asyncio.sleep(.005)


async def main(profile_path=None, trace=False):
    with tempfile.TemporaryDirectory(prefix="toad-cold-replay-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        wire(root / "wire").register(Thread("cold-replay", frozenset(), str(root), pid=os.getpid()))
        released = asyncio.Event()
        body = "## Saved response\n\n" + "Paragraph **with markup** and content.\n\n" * 10
        body += "```python\n" + "def calculate(value): return value + 1\n" * 60 + "```\n"
        events = tuple(TranscriptEvent("assistant", f"Record {i}\n\n" + body) for i in range(30))
        events += (TranscriptEvent("assistant", "LATEST_REPLAY_MARKER"),)
        page = TranscriptPage(events, TranscriptCursor("fixture", 0), TranscriptCursor("fixture", len(events)), False, False)

        async def start(agent, target):
            agent._message_target = target

            async def attach():
                await released.wait()
                target.post_message(TranscriptSnapshot(page.events, page))
                target.post_message(AgentReady())

            agent._task = asyncio.create_task(attach())

        app = ToadApp(project_dir=str(root))
        try:
            with patch.object(Agent, "start", start):
                async with app.run_test(size=(110, 35)) as pilot:
                    await pilot.pause()
                    owner = app.current_mode
                    app.screen._agent = {"name": "Fixture", "identity": "fixture", "short_name": "fixture",
                                         "run_command": {"*": "/bin/false"}, "protocol": "acp"}
                    mode = await app.open_thread_session(owner_mode=owner, project_path=root, target="cold-replay")
                    screen = app.screen
                    conversation = screen.conversation
                    await pilot.pause()
                    assert conversation.query(ThreadLoading), "Replay gate did not preserve loading UI"
                    gaps = []

                    async def heartbeat():
                        previous = time.perf_counter()
                        while True:
                            await asyncio.sleep(.005)
                            now = time.perf_counter()
                            gaps.append((now - previous) * 1000)
                            previous = now

                    pulse = asyncio.create_task(heartbeat())
                    await asyncio.sleep(0)
                    profiler = cProfile.Profile() if profile_path else None
                    if profiler:
                        profiler.enable()
                    try:
                        started = time.perf_counter()
                        released.set()
                        await until(lambda: conversation.agent_ready and any(
                            "LATEST_REPLAY_MARKER" in block.source for block in screen.query(AgentResponse)))
                        await pilot.pause()
                        replay = {"ready_ms": round((time.perf_counter() - started) * 1000, 2),
                                  "max_event_loop_gap_ms": round(max(gaps, default=0), 2)}
                        assert not conversation.query(ThreadLoading)
                        conversation.prompt.text = "retained draft"
                        returns = []
                        for updated in (False, True, False, True):
                            await app.switch_mode(owner)
                            if updated:
                                response = list(screen.query(AgentResponse))[-1]
                                await response.update(response.source + "\n\nNew background paragraph.")
                            await pilot.pause()
                            dirty = (screen._layout_required, len(screen._layout_widgets))
                            footer = screen.query_one(Footer)
                            before_footer = footer._binding_state
                            current_footer = footer._current_binding_state(screen)
                            footer_layout_pending = footer._layout_required
                            gaps.clear()
                            started = time.perf_counter()
                            stages = []
                            original_reflow = screen._compositor.reflow
                            original_refresh = Widget.refresh
                            original_size_updated = Footer._size_updated

                            def traced_size_updated(widget, size, virtual_size, container_size, layout=True):
                                if trace:
                                    stages.append({"footer_size_update": [str(widget._size), str(widget.virtual_size), str(widget._container_size)],
                                                   "requested": [str(size), str(virtual_size), str(container_size)],
                                                   "layout": layout})
                                return original_size_updated(widget, size, virtual_size, container_size, layout=layout)

                            def traced_refresh(widget, *args, **kwargs):
                                if trace and isinstance(widget, Footer) and kwargs.get("layout"):
                                    frame = sys._getframe(1)
                                    callers = []
                                    for _ in range(9):
                                        if frame is None:
                                            break
                                        callers.append((Path(frame.f_code.co_filename).name, frame.f_code.co_name, frame.f_lineno))
                                        frame = frame.f_back
                                    stages.append({"footer_refresh_callers": callers})
                                return original_refresh(widget, *args, **kwargs)

                            def traced_reflow(*args, **kwargs):
                                if trace:
                                    frame = sys._getframe(1)
                                    callers = []
                                    for _ in range(5):
                                        if frame is None:
                                            break
                                        callers.append((Path(frame.f_code.co_filename).name, frame.f_code.co_name, frame.f_lineno))
                                        frame = frame.f_back
                                    stages.append({"callers": callers, "invalidated": [type(widget).__name__ for widget in screen._layout_widgets]})
                                    stages[-1]["footer_binding_delta"] = (
                                        str(footer._binding_state != footer._current_binding_state(screen)))
                                    stages[-1]["footer_children"] = len(footer.children)
                                    stages[-1]["footer_layout_pending"] = footer._layout_required
                                return original_reflow(*args, **kwargs)

                            with patch.object(screen._compositor, "reflow", side_effect=traced_reflow) as reflow, ExitStack() as tracing:
                                if trace:
                                    tracing.enter_context(patch.object(Widget, "refresh", traced_refresh))
                                    tracing.enter_context(patch.object(Footer, "_size_updated", traced_size_updated))
                                await app.switch_mode(mode)
                                await pilot.pause()
                                returns.append({"updated": updated, "layout_before": dirty,
                                                "ready_ms": round((time.perf_counter() - started) * 1000, 2),
                                                "max_event_loop_gap_ms": round(max(gaps, default=0), 2),
                                                "full_reflows": reflow.call_count,
                                                "footer_state_changed_pre_switch": before_footer != current_footer,
                                                **({"footer_layout_pending_pre_switch": footer_layout_pending} if trace else {}),
                                                **({"stages": stages} if trace else {})})
                            assert conversation.prompt.text == "retained draft"
                        print(json.dumps({"boundary": "post-spinner replay and headless settled returns; not terminal pixels",
                                          "replay": replay, "returns": returns}, indent=2))
                    finally:
                        pulse.cancel()
                        await asyncio.gather(pulse, return_exceptions=True)
                        if profiler:
                            profiler.disable()
                            profiler.dump_stats(profile_path)
        finally:
            released.set()
        await asyncio.get_running_loop().shutdown_default_executor()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile")
    parser.add_argument("--trace", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.profile, args.trace))
