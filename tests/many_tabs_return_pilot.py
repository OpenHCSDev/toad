"""Observe creation, reverse first revisits, then forward and reverse warm returns."""

import argparse
import asyncio
from collections import Counter
from contextlib import ExitStack
import gc
import json
import os
from pathlib import Path
import statistics
import sys
import tempfile
import threading
import time
from types import FunctionType
from unittest.mock import patch
from weakref import ref

from agent_comms import Thread, TranscriptCursor, TranscriptEvent, TranscriptPage, wire
from runtime_fixture import ToadApp
from textual.widget import Widget
from toad.acp.agent import Agent
from toad.acp.messages import TranscriptSnapshot
from toad.agent import AgentReady
from toad import __file__ as toad_file
from toad.widgets.comms_sidebar import ChannelGroup, CommsSidebar
from toad.widgets.session_sidebar import ThreadStatusRow
from toad.widgets.session_tabs import SessionLabel, SessionsTabs
from toad.widgets.sidebar_tree import SidebarGroup
from toad.widgets.footer import Footer


class ReturnApp(ToadApp):
    CSS_PATH = Path(toad_file).parent / "toad.tcss"
    pending_display = None

    def _display(self, screen, renderable):
        super()._display(screen, renderable)
        pending = self.pending_display
        if (pending is not None and renderable is not None and not self._batch_count
                and screen is self.screen and self.current_mode == pending[0]):
            self.pending_display = None
            pending[1].set_result(time.perf_counter())


async def main(*, empty=False, trace=False, observe=False, output=None, peers=0, channels=0, cycles=1, gc_census=False, display_only=False):
    measurements = []
    with tempfile.TemporaryDirectory(prefix="toad-tab-return-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        targets = [f"return-{index}" for index in range(10)]
        for name in targets:
            wire(root / "wire").register(Thread(name, frozenset(), str(root), pid=os.getpid()))
        for index in range(peers):
            wire(root / "wire").register(Thread(f"peer-{index}", frozenset({"fixture"}), str(root), pid=os.getpid()))
        for index in range(channels):
            wire(root / "wire").set_channel(f"#fixture-{index}", frozenset({"fixture"}))
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

        app = ReturnApp(project_dir=str(root))
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

                passes = [(f"{cycle + 1}:" + phase if cycle else phase, order)
                          for cycle in range(cycles)
                          for phase, order in (("reverse-first", tuple(reversed(modes))),
                                               ("forward-second", tuple(modes)),
                                               ("reverse-third", tuple(reversed(modes))))]
                for phase, visits in passes:
                    for mode in visits:
                        if mode == app.current_mode:
                            continue
                        screen = app.get_screen_stack(mode)[0]
                        revision = screen._resume_style
                        current = screen._style_revision()
                        tabs = screen.query_one(SessionsTabs)
                        rows_before = {
                            (row.query_ancestor(ChannelGroup).row.target_name, row.thread_name): ref(row)
                            for row in screen.query(CommsSidebar).first().query(ThreadStatusRow)
                            if row.thread_name is not None
                        }
                        record = {"phase": phase, "mode": mode,
                                  "widgets_before": len(screen.query(Widget)),
                                  "tabs_before": len(screen.query(SessionLabel)),
                                  "style_revision_changed": revision != current,
                                  "css_generation": [revision.css_generation, current.css_generation],
                                  "css_sources": [len(revision.sources), len(current.sources)],
                                  "layout_before": screen._layout_required}
                        record["header_before"] = {"height": tabs.parent.size.height,
                                                   "tab_height": tabs.size.height,
                                                   "horizontal_scrollbar": tabs.show_horizontal_scrollbar}
                        mounts = Counter()
                        reflows = []
                        stale_reflows = []
                        discarded_renders = []
                        styles = Counter()
                        gaps = []
                        timed_events = []
                        collecting = {}
                        started = time.perf_counter()
                        original_mount = Widget.mount
                        original_reflow = screen._compositor.reflow
                        original_styles = app.stylesheet.update_nodes
                        original_render = screen._compositor.render_update
                        original_refresh = Widget.refresh

                        def gc_event(phase, info):
                            key = (threading.get_ident(), info["generation"])
                            if phase == "start":
                                frame = sys._getframe(1)
                                callers = []
                                for _ in range(10):
                                    if frame is None:
                                        break
                                    callers.append((Path(frame.f_code.co_filename).name, frame.f_code.co_name, frame.f_lineno))
                                    frame = frame.f_back
                                collecting[key] = (time.perf_counter(), callers, len(gc.garbage))
                            elif key in collecting:
                                begin, callers, garbage_start = collecting.pop(key)
                                event = {"operation": f"gc-generation-{key[1]}",
                                         "start_ms": round((begin - started) * 1000, 2),
                                         "duration_ms": round((time.perf_counter() - begin) * 1000, 2),
                                         "collected": info["collected"], "thread": key[0]}
                                if event["duration_ms"] >= 5:
                                    event["trigger"] = callers
                                if gc_census and info["collected"]:
                                    garbage = gc.garbage[garbage_start:]
                                    event["garbage_types"] = Counter(
                                        f"{type(obj).__module__}.{type(obj).__qualname__}" for obj in garbage).most_common(25)
                                    event["garbage_functions"] = Counter(
                                        f"{Path(obj.__code__.co_filename).name}:{obj.__qualname__}"
                                        for obj in garbage if isinstance(obj, FunctionType)).most_common(15)
                                timed_events.append(event)

                        def synchronous(name, function):
                            def measured(*args, **kwargs):
                                begin = time.perf_counter()
                                cpu = time.thread_time()
                                batch = app._batch_count
                                try:
                                    return function(*args, **kwargs)
                                finally:
                                    elapsed = (time.perf_counter() - begin) * 1000
                                    if elapsed >= 1:
                                        timed_events.append({"operation": name,
                                                             "batch_depth": batch,
                                                             "start_ms": round((begin - started) * 1000, 2),
                                                             "duration_ms": round(elapsed, 2),
                                                             "thread_cpu_ms": round((time.thread_time() - cpu) * 1000, 2)})
                            return measured

                        def asynchronous(name, function):
                            async def measured(*args, **kwargs):
                                begin = time.perf_counter()
                                try:
                                    return await function(*args, **kwargs)
                                finally:
                                    timed_events.append({"operation": name,
                                                         "start_ms": round((begin - started) * 1000, 2),
                                                         "duration_ms": round((time.perf_counter() - begin) * 1000, 2)})
                            return measured

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

                        def counted_render(*args, **kwargs):
                            if app._atomic_mode_switch and app._batch_count:
                                discarded_renders.append(time.perf_counter())
                            return original_render(*args, **kwargs)

                        def traced_refresh(widget, *args, **kwargs):
                            if kwargs.get("layout") and isinstance(widget, (Footer, SessionsTabs)):
                                frame = sys._getframe(1)
                                callers = []
                                for _ in range(7):
                                    if frame is None:
                                        break
                                    callers.append((Path(frame.f_code.co_filename).name, frame.f_code.co_name, frame.f_lineno))
                                    frame = frame.f_back
                                timed_events.append({"operation": "layout-request", "widget": type(widget).__name__,
                                                     "start_ms": round((time.perf_counter() - started) * 1000, 2),
                                                     "duration_ms": 0, "callers": callers})
                            return original_refresh(widget, *args, **kwargs)

                        async def heartbeat():
                            previous = time.perf_counter()
                            while True:
                                await asyncio.sleep(.005)
                                now = time.perf_counter()
                                gaps.append((now - previous) * 1000)
                                if trace and now - previous >= .02:
                                    timed_events.append({"operation": "heartbeat-gap",
                                                         "start_ms": round((previous - started) * 1000, 2),
                                                         "duration_ms": round((now - previous) * 1000, 2)})
                                previous = now

                        pulse = asyncio.create_task(heartbeat())
                        await asyncio.sleep(0)
                        try:
                            with ExitStack() as instrumentation:
                                instrumentation.enter_context(patch.object(Widget, "mount", counted_mount))
                                instrumentation.enter_context(patch.object(screen._compositor, "reflow", counted_reflow))
                                instrumentation.enter_context(patch.object(app.stylesheet, "update_nodes", counted_styles))
                                instrumentation.enter_context(patch.object(screen._compositor, "render_update", counted_render))
                                if trace:
                                    instrumentation.enter_context(patch.object(Widget, "refresh", traced_refresh))
                                    gc.callbacks.append(gc_event)
                                    instrumentation.callback(gc.callbacks.remove, gc_event)
                                    for instance, method in ((screen, "_refresh_layout"),
                                                             (screen._compositor, "render_update"),
                                                             (Widget, "mount"),
                                                             (app.stylesheet, "update_nodes")):
                                        instrumentation.enter_context(patch.object(
                                            instance, method, synchronous(method, getattr(instance, method))))
                                    for instance, method in ((screen, "prepare_navigation"),
                                                             (screen, "layout_navigation"),
                                                             (CommsSidebar, "_present_snapshot"),
                                                             (SidebarGroup, "reconcile_rows")):
                                        instrumentation.enter_context(patch.object(
                                            instance, method, asynchronous(method, getattr(instance, method))))
                                started = time.perf_counter()
                                displayed = asyncio.get_running_loop().create_future()
                                app.pending_display = (mode, displayed)
                                await app.switch_mode(mode)
                                record["switch_ms"] = round((time.perf_counter() - started) * 1000, 2)
                                if not display_only:
                                    await pilot.pause()
                                presented = await asyncio.wait_for(displayed, 5)
                                record["headless_display_ms"] = round((presented - started) * 1000, 2)
                                await asyncio.sleep(0)
                                record["settled_ms"] = round((time.perf_counter() - started) * 1000, 2)
                        finally:
                            pulse.cancel()
                            await asyncio.gather(pulse, return_exceptions=True)
                        record.update(max_loop_gap_ms=round(max(gaps, default=0), 2), mounts=dict(mounts),
                                      reflows=len(reflows), stale_roster_reflows=len(stale_reflows),
                                      discarded_navigation_renders=len(discarded_renders),
                                      styled_nodes=sum(styles.values()))
                        rows_after = {
                            (row.query_ancestor(ChannelGroup).row.target_name, row.thread_name): row
                            for row in screen.query(CommsSidebar).first().query(ThreadStatusRow)
                            if row.thread_name is not None
                        }
                        replaced_rows = [key for key, previous in rows_before.items()
                                         if key in rows_after and previous() is not rows_after[key]]
                        record["replaced_thread_rows"] = len(replaced_rows)
                        record["header_after"] = {"height": tabs.parent.size.height,
                                                  "tab_height": tabs.size.height,
                                                  "horizontal_scrollbar": tabs.show_horizontal_scrollbar}
                        if trace:
                            record.update(reflow_invalidations=reflows, styles=dict(styles),
                                          timed_events=timed_events)
                        measurements.append(record)
                        assert screen.conversation.prompt.text == f"draft-{mode}"
                        assert len(screen.query(SessionLabel)) == len(app.open_tabs)
                        if not observe:
                            assert not stale_reflows, (phase, mode, stale_reflows)
                            assert not discarded_renders, (phase, mode, "Rendered an intermediate frame that App discards")
                            assert not replaced_rows, (phase, mode, "Unchanged threads were remounted", replaced_rows)
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
                destination = app.get_screen_stack(modes[3])[0]
                retained = {row.thread_name: row for row in destination.query_one(CommsSidebar).query(ThreadStatusRow)
                            if row.thread_name is not None}
                for mode in modes[:3]:
                    await app.close_session_mode(mode)
                await app.switch_mode(modes[3])
                await pilot.pause()
                assert tuple(label.id for label in app.screen.query(SessionLabel)) == tuple(
                    tab.mode_name for tab in app.open_tabs
                )
                assert app.screen.conversation.prompt.text == f"draft-{modes[3]}"
                if not observe and not empty:
                    for row in app.screen.query_one(CommsSidebar).query(ThreadStatusRow):
                        if row.thread_name in targets[:3]:
                            assert row is retained[row.thread_name]
                            assert row.mode_name is None, "A closed view remained a navigation target"
                assert not app._atomic_mode_switch and app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    result = {"boundary": "headless switch/settlement; not terminal-presented frames",
              "empty": empty, "peers": peers, "channels": channels,
              "display_only": display_only, "returns": measurements}
    if output is not None:
        output.write_text(json.dumps(result, indent=2) + "\n")
    if trace and output is None:
        print(json.dumps(result, indent=2))
    else:
        for phase in dict.fromkeys(record["phase"] for record in measurements):
            records = [record for record in measurements if record["phase"] == phase]
            print(json.dumps({"phase": phase, "switch_median_ms": statistics.median(record["switch_ms"] for record in records),
                              "switch_max_ms": max(record["switch_ms"] for record in records),
                              "headless_display_median_ms": statistics.median(record["headless_display_ms"] for record in records),
                              "replaced_thread_rows": sum(record["replaced_thread_rows"] for record in records),
                              "reflows": [record["reflows"] for record in records],
                              "max_loop_gap_ms": max(record["max_loop_gap_ms"] for record in records)}))
        if trace:
            slowest = sorted(measurements, key=lambda record: record["max_loop_gap_ms"], reverse=True)[:3]
            print(json.dumps({"slowest": [
                {"phase": record["phase"], "mode": record["mode"], "switch_ms": record["switch_ms"],
                 "max_loop_gap_ms": record["max_loop_gap_ms"],
                 "timed_events": [event for event in record["timed_events"] if event["duration_ms"] >= 5]}
                for record in slowest]}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--empty", action="store_true")
    parser.add_argument("--trace", action="store_true")
    parser.add_argument("--observe", action="store_true", help="Record baseline layout counts without the catch-up gate")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--peers", type=int, default=0)
    parser.add_argument("--channels", type=int, default=0)
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--gc-census", action="store_true", help="Diagnostic-only retained garbage census; changes object lifetimes")
    parser.add_argument("--display-only", action="store_true", help="Observe native headless presentation without Pilot.pause during returns")
    args = parser.parse_args()
    previous_debug = gc.get_debug()
    try:
        if args.gc_census:
            gc.set_debug(previous_debug | gc.DEBUG_SAVEALL)
        asyncio.run(main(empty=args.empty, trace=args.trace, observe=args.observe, output=args.output,
                         peers=args.peers, channels=args.channels, cycles=args.cycles, gc_census=args.gc_census,
                         display_only=args.display_only))
    finally:
        if args.gc_census:
            gc.set_debug(previous_debug)
            gc.garbage.clear()
