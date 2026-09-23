"""Profile a real ACP thread attachment with a large inherited transcript.

Run with local agent-comms on PYTHONPATH. Optional --profile writes cProfile
stats; --trace measures Python allocation peak (adds substantial overhead).
"""

import argparse
import asyncio
import cProfile
import json
import os
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

from agent_comms import Thread
from agent_comms.operations import wire
from runtime_fixture import ToadApp
from toad.widgets.agent_response import AgentResponse
from toad.widgets.transcript_history import TranscriptHistory
from toad.widgets.conversation import ThreadLoading


class ProfileApp(ToadApp):
    open_started: float | None = None
    first_open_frame: float | None = None

    def _display(self, screen, renderable):
        if (self.open_started is not None and self.first_open_frame is None
                and renderable is not None and not self._batch_count
                and screen is self.screen and getattr(screen, "_agent_session_id", None) == "fork"
                and screen.query(ThreadLoading)):
            self.first_open_frame = time.perf_counter() - self.open_started
            if (profiler := getattr(self, "first_frame_profiler", None)) is not None:
                profiler.disable()
        return super()._display(screen, renderable)


async def main(args):
    with tempfile.TemporaryDirectory(prefix="toad-thread-profile-") as directory:
        root = Path(directory)
        os.environ.update(
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_STATE_HOME=str(root / "state"),
            XDG_DATA_HOME=str(root / "data"),
            AGENT_COMMS_ROOT=str(root / "wire"),
            AGENT_COMMS_AGENT_BIN="/bin/echo",
            AGENT_COMMS_AGENT_MODELS="test/model",
            AGENT_COMMS_AGENT_ARGS="--model test/model",
        )
        transcript = root / "fork.jsonl"
        text = (
            "## Analysis\n\n"
            + "- Investigate this implementation and verify behavior.\n" * 24
        )
        with transcript.open("w") as output:
            for index in range(args.messages):
                output.write(
                    json.dumps(
                        {
                            "type": "message",
                            "message": {
                                "role": "user" if index % 2 == 0 else "assistant",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": f"Record {index}\n\n{text}",
                                    }
                                ],
                            },
                        }
                    )
                    + "\n"
                )
            output.write(
                json.dumps(
                    {
                        "type": "message",
                        "message": {
                            "role": "assistant",
                            "content": [
                                {"type": "text", "text": "LATEST-REPLAY-MARKER"}
                            ],
                        },
                    }
                )
                + "\n"
            )
        comms = wire(root / "wire")
        comms.register(Thread(name="parent", tags=frozenset(), worktree=str(root)))
        comms.register(
            Thread(
                name="fork",
                parent="parent",
                tags=frozenset(),
                worktree=str(root),
                session_file=str(transcript),
            )
        )
        for index in range(args.wire_messages):
            comms.send("parent", "#all", f"coordination {index}: " + "status " * 100)
        if args.wire_messages:
            comms.acknowledge("fork")
        app = ProfileApp(project_dir=str(root))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            owner = app.current_mode
            app.screen._agent = {
                "name": "Profile",
                "identity": "profile",
                "short_name": "profile",
                "run_command": {"*": f"{sys.executable} -m agent_comms.acp"},
                "protocol": "acp",
            }
            ticks = []

            async def heartbeat():
                previous = time.perf_counter()
                while True:
                    await asyncio.sleep(0.02)
                    now = time.perf_counter()
                    ticks.append(now - previous)
                    previous = now

            pulse = asyncio.create_task(heartbeat())
            if args.trace:
                tracemalloc.start()
            profiler = cProfile.Profile() if args.profile else None
            if os.environ.get("TOAD_PROFILE_FIRST_FRAME"):
                app.first_frame_profiler = profiler
            if profiler:
                profiler.enable()
            started = time.perf_counter()
            app.open_started = started
            try:
                mode = await app.open_thread_session(
                    owner_mode=owner, project_path=root, target="fork"
                )
                async with asyncio.timeout(120):
                    while not (
                        app.screen.conversation.agent_ready
                        and any(
                            "LATEST-REPLAY-MARKER" in block.source
                            for block in app.screen.query(AgentResponse)
                        )
                    ):
                        await asyncio.sleep(0.05)
                await pilot.pause()
                elapsed = time.perf_counter() - started
                mounted = len(list(app.screen.conversation.query("*")))
                assert (
                    mounted < 300
                ), "Saved Markdown was eagerly expanded during attachment"
                peak = tracemalloc.get_traced_memory()[1] if args.trace else None
                await app.switch_mode(owner)
                switched = time.perf_counter()
                assert (
                    await app.open_thread_session(
                        owner_mode=owner, project_path=root, target="fork"
                    )
                    == mode
                )
                await pilot.pause()
                print(
                    json.dumps(
                        {
                            "messages": args.messages,
                            "file_bytes": transcript.stat().st_size,
                            "open_seconds": elapsed,
                            "first_loading_frame_seconds": app.first_open_frame,
                            "reopen_seconds": time.perf_counter() - switched,
                            "max_event_loop_gap_seconds": max(ticks, default=0),
                            "mounted_widgets": mounted,
                            "peak_python_bytes": peak,
                        },
                        indent=2,
                    )
                )
            finally:
                print(
                    json.dumps(
                        {
                            "elapsed": time.perf_counter() - started,
                            "ready": app.screen.conversation.agent_ready,
                            "widgets": len(list(app.screen.conversation.query("*"))),
                            "responses": len(list(app.screen.query(AgentResponse))),
                            "history": [
                                {"region": str(history.region), "older": history.has_older,
                                 "newer": history.has_newer, "loading": history._loading,
                                 "pages": [(p.start, p.stop, len(p.fragments)) for p in history.pages]}
                                for history in app.screen.query(TranscriptHistory)
                            ],
                            "last_sources": [
                                block.source[-100:]
                                for block in list(app.screen.query(AgentResponse))[-2:]
                            ],
                            "max_gap": max(ticks, default=0),
                        }
                    )
                )
                pulse.cancel()
                await asyncio.gather(pulse, return_exceptions=True)
                if profiler:
                    profiler.disable()
                    profiler.dump_stats(args.profile)
                if args.trace:
                    tracemalloc.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--messages", type=int, default=10000)
    parser.add_argument("--profile")
    parser.add_argument("--trace", action="store_true")
    parser.add_argument("--wire-messages", type=int, default=0)
    asyncio.run(main(parser.parse_args()))
