"""Observe creation, reverse first revisits, then forward and reverse warm returns."""

import argparse
import asyncio
from collections import Counter
from contextlib import ExitStack
import gc
from hashlib import sha256
from importlib.metadata import distribution
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from types import FunctionType
from unittest.mock import patch
from weakref import ref

from agent_comms.child_process import ProcessIdentity
from agent_comms.threads import Thread
from agent_comms.transcripts import TranscriptCursor, TranscriptPage
from agent_comms.transcript_events import AssistantTranscript
from agent_comms.comms import wire
from agent_comms import __file__ as comms_file
from runtime_fixture import ToadApp
from textual.widget import Widget
from textual.widgets import TextArea
from textual import __file__ as textual_file
from toad.acp.agent import Agent
from toad.acp.messages import TranscriptSnapshot
from toad.agent import AgentReady
from toad import __file__ as toad_file
from toad.widgets.comms_sidebar import ChannelGroup, CommsSidebar
from toad.widgets.session_sidebar import ThreadStatusRow
from toad.widgets.session_tabs import SessionLabel, SessionsTabs
from toad.widgets.sidebar_tree import SidebarGroup
from toad.widgets.footer import Footer
from toad.session_presentation import BlankSessionSurface
from toad.widgets.side_bar import SideBar
from toad.work_preparation import PreparationRuntime


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


async def main(*, empty=False, trace=False, observe=False, output=None, peers=0, channels=0, cycles=1,
               gc_census=False, display_only=False, tabs=10, source_threads=None, records=20,
               ownership_census=False, gc_observe=False, phase_only=False, phases=None):
    if tabs < 4 or (source_threads is not None and source_threads < tabs) or records < 1:
        raise ValueError("Use at least four tabs, source_threads >= tabs, and positive history records")
    measurements = []
    censuses = []
    run_started = time.perf_counter()

    def census(app, phase):
        if not ownership_census:
            return
        # Outside measured navigation. No collection, DEBUG_SAVEALL, retained
        # object references, or changed GC policy. Registry and heap differ.
        objects = gc.get_objects()
        tracked = len(objects)
        types = Counter(f"{type(obj).__module__}.{type(obj).__qualname__}" for obj in objects)
        del objects
        nodes = tuple(app._registry)
        counts = Counter(type(node).__name__ for node in nodes)
        active = sum(node.is_attached and node.screen is app.screen for node in nodes)
        censuses.append({"phase": phase, "tracked": tracked, "tracked_types": types.most_common(40),
                         "registered_widgets": len(nodes), "active_registered_widgets": active,
                         "registered_types": dict(counts),
                         "preparation": {key: getattr(app.preparation, key)
                                         for key in ("hits", "misses", "shared", "retained_bytes")}})
        print(json.dumps({"phase_completed": phase, "elapsed_s": round(time.perf_counter() - run_started, 2),
                          "switches_recorded": len(measurements), "widgets": len(nodes),
                          "labels": counts["SessionLabel"]}), flush=True)
    with tempfile.TemporaryDirectory(prefix="toad-tab-return-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        source_names = [f"return-{index}" for index in range(source_threads or tabs)]
        targets = source_names[:tabs]
        for name in source_names:
            wire(root / "wire").threads.register(Thread(name, frozenset(), str(root), process_identity=ProcessIdentity.capture(os.getpid())))
        for index in range(peers):
            wire(root / "wire").threads.register(Thread(f"peer-{index}", frozenset({"fixture", *(f"fixture-{i}" for i in range(channels))}), str(root), process_identity=ProcessIdentity.capture(os.getpid())))
        for index in range(channels):
            wire(root / "wire").channels.create_tag(f"fixture-{index}")
        body = "## Saved response\n\n" + "Paragraph **with markup** and content.\n\n" * 5
        body += "```python\n" + "def calculate(value): return value + 1\n" * 30 + "```\n"
        events = tuple(AssistantTranscript(f'Record {i}\n\n' + body) for i in range(records))
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

                census(app, "after-create")
                passes = [(f"{cycle + 1}:" + phase if cycle else phase, order)
                          for cycle in range(cycles)
                          for phase, order in (("reverse-first", tuple(reversed(modes))),
                                               ("forward-second", tuple(modes)),
                                               ("reverse-third", tuple(reversed(modes))))
                          if phases is None or phase in phases]
                for phase, visits in passes:
                    for mode in visits:
                        if mode == app.current_mode:
                            continue
                        screen = app.get_screen_stack(mode)[0]
                        revision = screen._resume_style
                        current = screen._style_revision()
                        tab_strip = app.screen.query_one(SessionsTabs)
                        rows_before = {
                            (row.query_ancestor(ChannelGroup).row.target_name, row.thread_name): ref(row)
                            for row in app.screen.query_one(CommsSidebar).query(ThreadStatusRow)
                            if row.thread_name is not None
                        }
                        record = {"phase": phase, "mode": mode,
                                  "widgets_before": len(screen.query(Widget)),
                                  "tabs_before": len(screen.query(SessionLabel)),
                                  "style_revision_changed": revision != current,
                                  "css_generation": [revision.css_generation, current.css_generation],
                                  "css_sources": [len(revision.sources), len(current.sources)],
                                  "layout_before": screen._layout_required}
                        record["header_before"] = {"height": tab_strip.parent.size.height,
                                                    "tab_height": tab_strip.size.height,
                                                    "horizontal_scrollbar": tab_strip.show_horizontal_scrollbar}
                        mounts = Counter()
                        reflows = []
                        stale_reflows = []
                        discarded_renders = []
                        styles = Counter()
                        gaps = []
                        timed_events = []
                        collecting = {}
                        changed_style_maps = 0
                        started = time.perf_counter()
                        original_mount = Widget.mount
                        original_reflow = screen._compositor.reflow
                        original_styles = app.stylesheet.update_nodes
                        original_render = screen._compositor.render_update
                        original_refresh = Widget.refresh

                        def gc_event(phase, info):
                            key = (threading.get_ident(), info["generation"])
                            if phase == "start":
                                callers = []
                                if trace:
                                    frame = sys._getframe(1)
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
                                cpu = time.thread_time()
                                origin, events = started, timed_events
                                work_type = type(args[1]).__name__ if name == "submit" else None
                                try:
                                    return await function(*args, **kwargs)
                                finally:
                                    events.append({"operation": name, "work_type": work_type,
                                                         "start_ms": round((begin - origin) * 1000, 2),
                                                         "duration_ms": round((time.perf_counter() - begin) * 1000, 2),
                                                         # Includes other UI tasks while awaiting;
                                                         # it is not exclusive CPU for this coroutine.
                                                         "ui_thread_cpu_during_span_ms": round((time.thread_time() - cpu) * 1000, 2)})
                            return measured

                        def counted_mount(widget, *children, **kwargs):
                            mounts.update(type(child).__name__ for child in children)
                            return original_mount(widget, *children, **kwargs)

                        def counted_reflow(*args, **kwargs):
                            reflows.append(dict(Counter(type(widget).__name__ for widget in screen._layout_widgets)))
                            desired = tuple(tab.mode_name for tab in app.open_tabs)
                            shown = tuple(label.id for label in screen.query(SessionLabel))
                            if shown != desired:
                                frame = sys._getframe(1)
                                callers = []
                                for _ in range(10):
                                    if frame is None:
                                        break
                                    callers.append((Path(frame.f_code.co_filename).name, frame.f_code.co_name, frame.f_lineno))
                                    frame = frame.f_back
                                stale_reflows.append({"shown": shown, "desired": desired,
                                                      "callers": callers, "batch_depth": app._batch_count,
                                                      "atomic_switch": app._atomic_mode_switch})
                            return original_reflow(*args, **kwargs)

                        def counted_styles(nodes, *args, **kwargs):
                            nonlocal changed_style_maps
                            nodes = list(nodes)
                            styles.update(type(node).__name__ for node in nodes)
                            previous = [dict(node.styles.get_rules()) for node in nodes] if trace else ()
                            result = original_styles(nodes, *args, **kwargs)
                            if trace:
                                changed_style_maps += sum(before != node.styles.get_rules()
                                                          for node, before in zip(nodes, previous))
                            return result

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
                                if trace or gc_observe:
                                    gc.callbacks.append(gc_event)
                                    instrumentation.callback(gc.callbacks.remove, gc_event)
                                if trace:
                                    instrumentation.enter_context(patch.object(Widget, "refresh", traced_refresh))
                                    for instance, method in ((screen, "_refresh_layout"),
                                                              (screen._compositor, "render_update"),
                                                              (Widget, "mount"),
                                                              (Widget, "reparent"),
                                                              (TextArea, "restore_editor_state"),
                                                              (SideBar, "_apply_layout"),
                                                              (app.stylesheet, "update_nodes")):
                                        instrumentation.enter_context(patch.object(
                                            instance, method, synchronous(method, getattr(instance, method))))
                                    for instance, method in ((screen, "prepare_navigation"),
                                                              (screen, "prepare_presentation"),
                                                              (screen, "layout_navigation"),
                                                              (BlankSessionSurface, "activate"),
                                                              (SessionsTabs, "_sync_tabs"),
                                                              (PreparationRuntime, "submit"),
                                                              (CommsSidebar, "_present_snapshot"),
                                                             (SidebarGroup, "reconcile_rows")):
                                        instrumentation.enter_context(patch.object(
                                            instance, method, asynchronous(method, getattr(instance, method))))
                                started = time.perf_counter()
                                switch_cpu = time.thread_time()
                                displayed = asyncio.get_running_loop().create_future()
                                app.pending_display = (mode, displayed)
                                await app.switch_mode(mode)
                                record["switch_ms"] = round((time.perf_counter() - started) * 1000, 2)
                                record["switch_ui_cpu_ms"] = round((time.thread_time() - switch_cpu) * 1000, 2)
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
                                      styled_nodes=sum(styles.values()),
                                      gc_max_ms=max((event["duration_ms"] for event in timed_events
                                                     if event["operation"].startswith("gc-generation-")), default=0),
                                      stale_reflow_details=stale_reflows[:3],
                                      changed_native_style_rule_maps=changed_style_maps if trace else None)
                        rows_after = {
                            (row.query_ancestor(ChannelGroup).row.target_name, row.thread_name): row
                            for row in app.screen.query_one(CommsSidebar).query(ThreadStatusRow)
                            if row.thread_name is not None
                        }
                        replaced_rows = [key for key, previous in rows_before.items()
                                         if key in rows_after and previous() is not rows_after[key]]
                        record["replaced_thread_rows"] = len(replaced_rows)
                        record["header_after"] = {"height": tab_strip.parent.size.height,
                                                  "tab_height": tab_strip.size.height,
                                                  "horizontal_scrollbar": tab_strip.show_horizontal_scrollbar}
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
                    census(app, phase)
                    if output is not None:
                        output.with_suffix(".phases.json").write_text(json.dumps({
                            "completed": False, "phase_completed": phase,
                            "boundary": "phase-only headless diagnostic; post-switch/teardown unverified",
                            "tabs": tabs, "empty": empty, "source_threads": source_threads or tabs,
                            "history_records": records, "peers": peers, "channels": channels,
                            "gc_observation": trace or gc_observe,
                            "instrumentation": "detailed timing/rule-map copies" if trace else "lightweight counts",
                            "returns": measurements, "ownership_censuses": censuses,
                        }, indent=2) + "\n")

                if output is not None:
                    # A distinct, explicitly incomplete phase receipt survives
                    # bounded teardown stalls without masquerading as acceptance.
                    output.with_suffix(".phases.json").write_text(json.dumps({
                        "completed": False, "phase": "before-close-checks",
                        "tabs": tabs, "empty": empty, "returns": measurements,
                        "ownership_censuses": censuses,
                    }, indent=2) + "\n")

                if not phase_only:
                    await verify_post_switch(app, pilot, modes, empty, observe, targets, run_started,
                                             ownership_census)
        await asyncio.get_running_loop().shutdown_default_executor()
        if ownership_census:
            print(json.dumps({"phase_completed": "executor-shutdown", "elapsed_s": round(time.perf_counter() - run_started, 2)}), flush=True)
    result = {"completed": True,
               "boundary": "headless switch/settlement; not terminal-presented frames",
               "empty": empty, "peers": peers, "channels": channels,
               "tabs": tabs, "source_threads": source_threads or tabs, "history_records": records,
               "ownership_censuses": censuses,
               "gc_observation": trace or gc_observe,
               "observation_only": observe,
               "phase_only": phase_only,
               "phase_filter": sorted(phases) if phases is not None else None,
               "instrumentation": "detailed timing/rule-map copies" if trace else "lightweight counts",
               "display_only": display_only, "returns": measurements}
    result["provenance"] = {
        "python": sys.version, "executable": sys.executable,
        "gc_thresholds": gc.get_threshold(), "gc_debug": gc.get_debug(),
        "probe_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "toad_source": toad_file,
        "toad_head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True,
                                               cwd=Path(toad_file).parents[2]).strip(),
        "textual_source": textual_file,
        "textual_head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True,
                                                  cwd=Path(textual_file).parents[2]).strip(),
        "source_status": subprocess.check_output(["git", "status", "--short"], text=True,
                                                   cwd=Path(toad_file).parents[2]),
        "core_install": json.loads(distribution("agent-comms").read_text("direct_url.json") or "null"),
        "core_source": comms_file,
    }
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


async def verify_post_switch(app, pilot, modes, empty, observe, targets, run_started, ownership_census):
    """Retain the original resize/same-mode/close and source-route assertions."""
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

    hidden_sidebar = app.screen.query_one(CommsSidebar)
    retained_channels = dict(hidden_sidebar._row_map)
    assert retained_channels
    assert all(row.is_attached for row in retained_channels.values())
    for mode in modes[:3]:
        if ownership_census:
            print(json.dumps({"closing": mode, "elapsed_s": round(time.perf_counter() - run_started, 2)}), flush=True)
        await app.close_session_mode(mode)
        if ownership_census:
            print(json.dumps({"closed": mode, "elapsed_s": round(time.perf_counter() - run_started, 2)}), flush=True)
    await app.switch_mode(modes[3])
    async with asyncio.timeout(5):
        await hidden_sidebar.navigation_ready.wait()
    await pilot.pause()
    assert all(hidden_sidebar._row_map[key] is row for key, row in retained_channels.items())
    assert tuple(label.id for label in app.screen.query(SessionLabel)) == tuple(
        tab.mode_name for tab in app.open_tabs
    )
    assert app.screen.conversation.prompt.text == f"draft-{modes[3]}"
    if not observe and not empty:
        rebuilt = {
            (row.query_ancestor(ChannelGroup).row.target_name, row.thread_name): row
            for row in hidden_sidebar.query(ThreadStatusRow)
            if row.thread_name in targets
        }
        assert {name for _, name in rebuilt} == set(targets), rebuilt
        expected_modes = dict(zip(targets[3:], modes[3:]))
        for (_, name), row in rebuilt.items():
            assert row.mode_name == expected_modes.get(name), (name, row.mode_name, expected_modes.get(name))
        await hidden_sidebar.sync_sessions()
        refreshed = {
            (row.query_ancestor(ChannelGroup).row.target_name, row.thread_name): row
            for row in hidden_sidebar.query(ThreadStatusRow)
            if row.thread_name in targets
        }
        assert refreshed.keys() == rebuilt.keys()
        assert all(refreshed[key] is row for key, row in rebuilt.items())
    assert not app._atomic_mode_switch and app._exception is None
    if ownership_census:
        print(json.dumps({"phase_completed": "close-checks", "elapsed_s": round(time.perf_counter() - run_started, 2)}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--empty", action="store_true")
    parser.add_argument("--trace", action="store_true")
    parser.add_argument("--observe", action="store_true", help="Report stale-layout/discarded-render evidence without failing those optimization assertions")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--peers", type=int, default=0)
    parser.add_argument("--channels", type=int, default=0)
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--gc-census", action="store_true", help="Diagnostic-only retained garbage census; changes object lifetimes")
    parser.add_argument("--display-only", action="store_true", help="Observe native headless presentation without Pilot.pause during returns")
    parser.add_argument("--tabs", type=int, default=10)
    parser.add_argument("--source-threads", type=int, help="Hold the source cohort fixed while varying mounted tabs")
    parser.add_argument("--records", type=int, default=20)
    parser.add_argument("--ownership-census", action="store_true", help="Sample registered widgets and tracked types outside timed navigation")
    parser.add_argument("--gc-observe", action="store_true", help="Observe ordinary GC durations without stack capture or policy changes")
    parser.add_argument("--phase-only", action="store_true", help="Diagnostic: skip resize/close acceptance after timed visit phases")
    parser.add_argument("--phases", nargs="+", choices=("reverse-first", "forward-second", "reverse-third"),
                        help="Diagnostic: select visit phases; omitted runs all three")
    args = parser.parse_args()
    previous_debug = gc.get_debug()
    try:
        if args.gc_census:
            gc.set_debug(previous_debug | gc.DEBUG_SAVEALL)
        asyncio.run(main(empty=args.empty, trace=args.trace, observe=args.observe, output=args.output,
                          peers=args.peers, channels=args.channels, cycles=args.cycles, gc_census=args.gc_census,
                          display_only=args.display_only, tabs=args.tabs, source_threads=args.source_threads,
                          records=args.records, ownership_census=args.ownership_census, gc_observe=args.gc_observe,
                          phase_only=args.phase_only, phases=frozenset(args.phases) if args.phases else None))
    finally:
        if args.gc_census:
            gc.set_debug(previous_debug)
            gc.garbage.clear()
