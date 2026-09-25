"""Observe creation, reverse first revisits, then forward and reverse warm returns."""

import argparse
import asyncio
from collections import Counter
from contextlib import ExitStack
import json
import os
from pathlib import Path
import statistics
import tempfile
import time
from unittest.mock import patch

from agent_comms import Thread, TranscriptCursor, TranscriptEvent, TranscriptPage, wire
from runtime_fixture import ToadApp
from textual.widget import Widget
from toad.acp.agent import Agent
from toad.acp.messages import TranscriptSnapshot
from toad.agent import AgentReady
from toad.widgets.session_tabs import SessionLabel


async def main(*, empty=False, trace=False, observe=False, output=None):
    measurements = []
    with tempfile.TemporaryDirectory(prefix="toad-tab-return-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        targets = [f"return-{index}" for index in range(10)]
        for name in targets:
            wire(root / "wire").register(Thread(name, frozenset(), str(root), pid=os.getpid()))
        body = "## Saved response\n\n" + "Paragraph **with markup** and content.\n\n" * 5
        body += "```python\n" + "def calculate(value): return value + 1\n" * 30 + "```\n"
        events = tuple(TranscriptEvent("assistant", f"Record {i}\n\n" + body) for i in range(20))
        page = TranscriptPage(events, TranscriptCursor("fixture", 0),
                              TranscriptCursor("fixture", len(events)), False, False)

        async def start(agent, target):
            agent._message_target = target

            async def deliver():
                target.post_message(TranscriptSnapshot(page.events, page))
                target.post_message(AgentReady())

            agent._task = asyncio.create_task(deliver())

        app = ToadApp(project_dir=str(root))
        with patch.object(Agent, "start", start):
            async with app.run_test(size=(110, 37)) as pilot:
                await pilot.pause()
                owner = app.current_mode
                app.screen._agent = {"name": "Fixture", "identity": "fixture", "short_name": "fixture",
                                     "run_command": {"*": "/bin/false"}, "protocol": "acp"}
                modes = []
                for name in targets:
                    if empty:
                        mode = (await app.new_session_screen(app.get_main_screen)).mode_name
                    else:
                        mode = await app.open_thread_session(owner_mode=owner, project_path=root, target=name)
                        async with asyncio.timeout(20):
                            while not app.screen.conversation.agent_ready:
                                await asyncio.sleep(.005)
                    modes.append(mode)
                    app.screen.conversation.prompt.text = f"draft-{mode}"
                    await pilot.pause()

                for phase, visits in (("reverse-first", reversed(modes)),
                                      ("forward-second", iter(modes)),
                                      ("reverse-third", reversed(modes))):
                    for mode in visits:
                        if mode == app.current_mode:
                            continue
                        screen = app.get_screen_stack(mode)[0]
                        revision = screen._resume_style
                        current = screen._style_revision()
                        record = {"phase": phase, "mode": mode,
                                  "widgets_before": len(screen.query(Widget)),
                                  "tabs_before": len(screen.query(SessionLabel)),
                                  "style_revision_changed": revision != current,
                                  "css_generation": [revision.css_generation, current.css_generation],
                                  "css_sources": [len(revision.sources), len(current.sources)],
                                  "layout_before": screen._layout_required}
                        mounts = Counter()
                        reflows = []
                        stale_reflows = []
                        styles = Counter()
                        gaps = []
                        original_mount = Widget.mount
                        original_reflow = screen._compositor.reflow
                        original_styles = app.stylesheet.update_nodes

                        def counted_mount(widget, *children, **kwargs):
                            mounts.update(type(child).__name__ for child in children)
                            return original_mount(widget, *children, **kwargs)

                        def counted_reflow(*args, **kwargs):
                            reflows.append(dict(Counter(type(widget).__name__ for widget in screen._layout_widgets)))
                            desired = tuple(tab.mode_name for tab in app.open_tabs)
                            shown = tuple(label.id for label in screen.query(SessionLabel))
                            if shown != desired:
                                stale_reflows.append({"shown": shown, "desired": desired})
                            return original_reflow(*args, **kwargs)

                        def counted_styles(nodes, *args, **kwargs):
                            nodes = list(nodes)
                            styles.update(type(node).__name__ for node in nodes)
                            return original_styles(nodes, *args, **kwargs)

                        async def heartbeat():
                            previous = time.perf_counter()
                            while True:
                                await asyncio.sleep(.005)
                                now = time.perf_counter()
                                gaps.append((now - previous) * 1000)
                                previous = now

                        pulse = asyncio.create_task(heartbeat())
                        await asyncio.sleep(0)
                        try:
                            with ExitStack() as instrumentation:
                                instrumentation.enter_context(patch.object(Widget, "mount", counted_mount))
                                instrumentation.enter_context(patch.object(screen._compositor, "reflow", counted_reflow))
                                instrumentation.enter_context(patch.object(app.stylesheet, "update_nodes", counted_styles))
                                started = time.perf_counter()
                                await app.switch_mode(mode)
                                record["switch_ms"] = round((time.perf_counter() - started) * 1000, 2)
                                await pilot.pause()
                                record["settled_ms"] = round((time.perf_counter() - started) * 1000, 2)
                        finally:
                            pulse.cancel()
                            await asyncio.gather(pulse, return_exceptions=True)
                        record.update(max_loop_gap_ms=round(max(gaps, default=0), 2), mounts=dict(mounts),
                                      reflows=len(reflows), stale_roster_reflows=len(stale_reflows),
                                      styled_nodes=sum(styles.values()))
                        if trace:
                            record.update(reflow_invalidations=reflows, styles=dict(styles))
                        measurements.append(record)
                        assert screen.conversation.prompt.text == f"draft-{mode}"
                        assert len(screen.query(SessionLabel)) == len(app.open_tabs)
                        if not observe:
                            assert not stale_reflows, (phase, mode, stale_reflows)
                        assert app._exception is None

                # Real geometry changes must survive the deferred activation
                # pass. Also exercise a same-mode request from the screen's own
                # message queue: navigation must not wait on that blocked queue.
                await pilot.resize_terminal(96, 31)
                await app.switch_mode(modes[-1])
                await pilot.pause()
                assert app.screen.size == app.size
                finished = asyncio.Event()

                async def same_mode():
                    await app.switch_mode(app.current_mode)
                    finished.set()

                app.screen.call_later(same_mode)
                await asyncio.wait_for(finished.wait(), 3)
                assert not app._atomic_mode_switch

                # A hidden roster may be missing new tabs AND retain several
                # closed ones. Bulk removal must preserve the remaining order.
                for mode in modes[:3]:
                    await app.close_session_mode(mode)
                await app.switch_mode(modes[3])
                await pilot.pause()
                assert tuple(label.id for label in app.screen.query(SessionLabel)) == tuple(
                    tab.mode_name for tab in app.open_tabs
                )
                assert app.screen.conversation.prompt.text == f"draft-{modes[3]}"
                assert not app._atomic_mode_switch and app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    result = {"boundary": "headless switch/settlement; not terminal-presented frames",
              "empty": empty, "returns": measurements}
    if output is not None:
        output.write_text(json.dumps(result, indent=2) + "\n")
    if trace:
        print(json.dumps(result, indent=2))
    else:
        for phase in dict.fromkeys(record["phase"] for record in measurements):
            records = [record for record in measurements if record["phase"] == phase]
            print(json.dumps({"phase": phase, "switch_median_ms": statistics.median(record["switch_ms"] for record in records),
                              "switch_max_ms": max(record["switch_ms"] for record in records),
                              "reflows": [record["reflows"] for record in records],
                              "max_loop_gap_ms": max(record["max_loop_gap_ms"] for record in records)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--empty", action="store_true")
    parser.add_argument("--trace", action="store_true")
    parser.add_argument("--observe", action="store_true", help="Record baseline layout counts without the catch-up gate")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    asyncio.run(main(empty=args.empty, trace=args.trace, observe=args.observe, output=args.output))
