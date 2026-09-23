"""Paint-level latency for scrolling and text selection in a rich transcript."""

import asyncio
import cProfile
import json
import os
import statistics
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import psutil
from textual import events
from textual.geometry import Offset

from runtime_fixture import ToadApp
from toad.widgets.agent_response import AgentResponse


class PaintProbe(ToadApp):
    CSS_PATH = Path(__file__).resolve().parents[1] / "src/toad/toad.tcss"
    next_paint: asyncio.Future[float] | None = None
    selection_profiler: cProfile.Profile | None = None

    def _display(self, screen, renderable):
        if (self.next_paint is not None and not self.next_paint.done()
                and screen is self.screen and renderable is not None and not self._batch_count):
            self.next_paint.set_result(time.perf_counter())
            if self.selection_profiler is not None:
                self.selection_profiler.disable()
        return super()._display(screen, renderable)


async def measure_baseline(app, pilot, conversation):
    conversation.window.anchor()
    await pilot.pause()
    widget_count = len(list(app.screen.walk_children()))
    assert widget_count > 200, widget_count
    scroll_times = []
    for _ in range(12):
        painted = app.next_paint = asyncio.get_running_loop().create_future()
        started = time.perf_counter()
        conversation.window.scroll_relative(y=-3, animate=False, immediate=True)
        scroll_times.append((await asyncio.wait_for(painted, 5) - started) * 1000)
        app.next_paint = None
        assert not conversation.window.follows_tail

    # Native pointer selection updates real Textual highlights.
    viewport = conversation.window.content_region
    screen = app.screen
    content = [item for item in screen.query("MarkdownParagraph")
               if item.region.overlaps(viewport) and item.region.y >= viewport.y + 2]
    assert len(content) >= 2, len(content)
    first, last = content[0], content[min(3, len(content) - 1)]
    await pilot.mouse_down(first, offset=(1, 0))
    painted = app.next_paint = asyncio.get_running_loop().create_future()
    profile_path = os.environ.get("TOAD_SELECT_PROFILE")
    if profile_path:
        app.selection_profiler = cProfile.Profile()
        app.selection_profiler.enable()
    started = time.perf_counter()
    x, y = last.region.x + 3, last.region.y
    app.mouse_position = Offset(x, y)
    screen._forward_event(events.MouseMove(None, x, y, 2, 1, 1, False, False, False))
    select_ms = (await asyncio.wait_for(painted, 5) - started) * 1000
    app.next_paint = None
    if app.selection_profiler is not None:
        app.selection_profiler.dump_stats(profile_path)
    await pilot.mouse_up(last, offset=(3, 0))
    assert screen.get_selected_text() and app._exception is None
    print(json.dumps({"widgets": widget_count,
                      "scroll_first_paint_median_ms": round(statistics.median(scroll_times), 1),
                      "scroll_first_paint_max_ms": round(max(scroll_times), 1),
                      "selection_first_paint_ms": round(select_ms, 1)}, indent=2))


async def main():
    # Exercise transcript painting independently of a concurrently changing
    # coordination snapshot implementation when explicitly requested.
    skip_comms = os.environ.get("TOAD_BENCH_SKIP_COMMS") == "1"
    if skip_comms:
        from toad.widgets.comms_sidebar import CommsSidebar

        async def skip_snapshot(self, revision):
            return None

        CommsSidebar._read_snapshot = skip_snapshot
    with tempfile.TemporaryDirectory(prefix="toad-scroll-select-latency-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        app = PaintProbe(project_dir=str(root))
        layout_events = []
        phase = [None]
        phase_started = [0.0]
        scroll_call_ms = {}
        scroll_profile_path = os.environ.get("TOAD_SCROLL_PROFILE")
        scroll_profiler = cProfile.Profile() if scroll_profile_path else None
        if os.environ.get("TOAD_BENCH_TRACE_REFLOW") == "1":
            from toad.screens.session_view import SessionView

            original_refresh = SessionView._refresh_layout

            def traced_refresh(screen, size=None, scroll=False):
                current = phase[0]
                visible_only = bool(scroll and not screen._layout_widgets)
                started = time.perf_counter()
                try:
                    return original_refresh(screen, size, scroll)
                finally:
                    if current is not None and screen.is_active:
                        layout_events.append({"phase": current,
                                              "visible_only": visible_only,
                                              "layout_widgets": len(screen._layout_widgets),
                                              "start_offset_ms": round((started - phase_started[0]) * 1000, 1),
                                              "elapsed_ms": round((time.perf_counter() - started) * 1000, 1)})

            SessionView._refresh_layout = traced_refresh
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            # Selection still uses native Textual hit-testing and copy text,
            # but pyperclip/xclip must not retain the runner's stdout pipe.
            app.settings.set("ui.auto_copy", False)
            conversation = app.screen.conversation
            replies = int(os.environ.get("TOAD_BENCH_RESPONSES", "4"))
            age_sweep = os.environ.get("TOAD_BENCH_AGE_SWEEP") == "1"
            stages = ([int(value) for value in os.environ.get(
                "TOAD_BENCH_AGE_STAGES", "4,16,64,128").split(",")]
                if age_sweep else [replies])
            stages = sorted(set(stages))
            mounted = 0
            violations = []
            auto_scroll_selection = os.environ.get("TOAD_BENCH_AUTOSCROLL_SELECTION") == "1"
            items_per_reply = int(os.environ.get("TOAD_BENCH_ITEMS_PER_REPLY", "20"))
            cross_reply = os.environ.get("TOAD_BENCH_CROSS_REPLY_SELECTION") == "1"
            for target in stages:
                if target <= mounted:
                    raise ValueError("Age stages must increase the reply count")
                await conversation.contents.mount(*[
                    AgentResponse(f"## Reply {i}\n\n" + "\n".join(
                        f"- item {j} " + "wrapped body " * 12 for j in range(items_per_reply)
                    ), paginate=False)
                    for i in range(mounted, target)
                ])
                mounted = target
                conversation.window.anchor()
                await pilot.pause()
                if age_sweep:
                    window = conversation.window
                    timings = []
                    for index in range(12):
                        painted = app.next_paint = asyncio.get_running_loop().create_future()
                        started = time.perf_counter()
                        phase[0] = (target, "near_latest_scroll", index)
                        phase_started[0] = started
                        if scroll_profiler is not None:
                            scroll_profiler.enable()
                        window.scroll_relative(y=-3, animate=False, immediate=True)
                        scroll_call_ms[phase[0]] = round((time.perf_counter() - started) * 1000, 1)
                        timings.append((await asyncio.wait_for(painted, 5) - started) * 1000)
                        if scroll_profiler is not None:
                            scroll_profiler.disable()
                        app.next_paint = None
                        phase[0] = None
                    older_position = window.scroll_y
                    window.scroll_to(y=0, animate=False, immediate=True)
                    await pilot.pause()
                    older_timings = []
                    for index in range(12):
                        painted = app.next_paint = asyncio.get_running_loop().create_future()
                        started = time.perf_counter()
                        phase[0] = (target, "near_oldest_scroll", index)
                        phase_started[0] = started
                        if scroll_profiler is not None:
                            scroll_profiler.enable()
                        window.scroll_relative(y=3, animate=False, immediate=True)
                        scroll_call_ms[phase[0]] = round((time.perf_counter() - started) * 1000, 1)
                        older_timings.append((await asyncio.wait_for(painted, 5) - started) * 1000)
                        if scroll_profiler is not None:
                            scroll_profiler.disable()
                        app.next_paint = None
                        phase[0] = None
                    assert window.scroll_y > 0, "Fixture did not scroll from old history"
                    window.anchor()
                    await pilot.pause()
                    viewport = window.content_region
                    visible = [item for item in app.screen.query("MarkdownParagraph")
                               if window in item.ancestors and item.region.overlaps(viewport)
                               and item.region.y >= viewport.y + 2]
                    assert len(visible) >= 2, len(visible)
                    first = visible[0]
                    first_reply = first.query_ancestor(AgentResponse)
                    if cross_reply:
                        last = next((item for item in reversed(visible)
                                     if item.query_ancestor(AgentResponse) is not first_reply), None)
                        assert last is not None, "Fixture cannot select across replies in this viewport"
                    else:
                        last = visible[min(3, len(visible) - 1)]
                    selection_timings = []
                    for _ in range(8):
                        await pilot.mouse_down(first, offset=(1, 0))
                        painted = app.next_paint = asyncio.get_running_loop().create_future()
                        started = time.perf_counter()
                        phase[0] = (target, "selection", len(selection_timings))
                        x, y = last.region.x + 3, last.region.y
                        app.mouse_position = Offset(x, y)
                        app.screen._forward_event(events.MouseMove(None, x, y, 2, 1, 1, False, False, False))
                        selection_timings.append((await asyncio.wait_for(painted, 5) - started) * 1000)
                        app.next_paint = None
                        phase[0] = None
                        await pilot.mouse_up(last, offset=(3, 0))
                    assert app.screen.get_selected_text(), "Selection lost text"
                    select_state = app.screen._select_state
                    accelerated = select_state._walk_viewport_widgets()
                    with patch.object(type(select_state), "_walk_viewport_widgets", return_value=None):
                        native_selected = select_state._walk_selected_widgets()
                    if accelerated is not None:
                        assert accelerated == native_selected, "Viewport path changed selected widget order"
                    if os.environ.get("TOAD_BENCH_FAST_SELECTION_DEBUG") == "1":
                        region = window.content_region
                        start_widget = select_state.start.content_widget
                        end_widget = select_state.end.content_widget
                        print(json.dumps({"start_region": str(start_widget.region),
                                          "end_region": str(end_widget.region),
                                          "window_region": str(region),
                                          "start_inside": region.contains_region(start_widget.region),
                                          "end_inside": region.contains_region(end_widget.region),
                                          "start_point_inside": region.contains_point(select_state.start.pointer_start_offset),
                                          "end_point_inside": region.contains_point(select_state.screen_offset),
                                          "start_mapped": start_widget in app.screen._compositor.visible_widgets,
                                          "end_mapped": end_widget in app.screen._compositor.visible_widgets,
                                          "common_scroll_ancestors": [(type(node).__name__, str(node.content_region),
                                              node.max_scroll_y, node.max_scroll_x)
                                              for node in start_widget.ancestors
                                              if node in end_widget.ancestors and getattr(node, "is_scrollable", False)],
                                          "nested_scrollers": [type(widget).__name__
                                              for widget in app.screen._compositor.visible_widgets
                                              if widget is not window and widget.is_scrollable
                                              and (widget.max_scroll_y > 0 or widget.max_scroll_x > 0)
                                              and select_state.selection_bounds.overlaps(widget.region)]}))
                    visible_selected = sorted(
                        (widget for widget in app.screen._compositor.visible_widgets
                         if not widget.is_container and widget.allow_select
                         and select_state.select_container in widget.ancestors
                         and select_state.selection_bounds.overlaps(widget.content_region)),
                        key=lambda widget: widget._selection_order,
                    )
                    for action, samples in (("near_latest_scroll", timings),
                                            ("near_oldest_scroll", older_timings),
                                            ("selection", selection_timings)):
                        if max(samples) >= 16:
                            violations.append((target, action, round(max(samples), 1)))
                    print(json.dumps({"replies": target,
                                      "widgets": len(list(app.screen.walk_children())),
                                      "selection_across_replies": cross_reply,
                                      "selection_container": type(select_state.select_container).__name__,
                                      "selected_widget_count": len(app.screen.selections),
                                      "visible_map_widgets": len(app.screen._compositor._visible_map or {}),
                                      "visible_selection_matches": native_selected == visible_selected,
                                      "viewport_selection_fast_path": accelerated is not None,
                                      "native_selected": len(native_selected),
                                      "visible_selected": len(visible_selected),
                                      "items_per_reply": items_per_reply,
                                      "rss_mib": round(psutil.Process().memory_info().rss / 2**20, 1),
                                      "older_scroll_y": older_position,
                                      "near_latest_scroll_median_ms": round(statistics.median(timings), 1),
                                      "near_latest_scroll_max_ms": round(max(timings), 1),
                                      "near_oldest_scroll_median_ms": round(statistics.median(older_timings), 1),
                                      "near_oldest_scroll_max_ms": round(max(older_timings), 1),
                                      "selection_median_ms": round(statistics.median(selection_timings), 1),
                                      "selection_max_ms": round(max(selection_timings), 1)}))
                    if os.environ.get("TOAD_BENCH_TRACE_REFLOW") == "1":
                        all_actions = {"near_latest_scroll": timings,
                                       "near_oldest_scroll": older_timings,
                                       "selection": selection_timings}
                        print(json.dumps({"replies": target,
                                          "slowest_frames": [
                                              {"action": action, "index": index,
                                               "frame_ms": round(samples[index], 1),
                                               "call_ms": scroll_call_ms.get((target, action, index)),
                                               "layout": [entry for entry in layout_events
                                                          if entry["phase"] == (target, action, index)]}
                                              for action, samples in all_actions.items()
                                              for index in sorted(range(len(samples)),
                                                                  key=samples.__getitem__, reverse=True)[:3]
                                          ]}))
                    if auto_scroll_selection and target == stages[-1]:
                        from textual.selection import SelectState

                        start_widget = last
                        await pilot.mouse_down(start_widget, offset=(1, 0))
                        window.scroll_relative(y=-window.size.height * 3, animate=False, immediate=True)
                        await pilot.pause()
                        assert not start_widget.region.overlaps(window.content_region)
                        older_widgets = [item for item in app.screen.query("MarkdownParagraph")
                                         if window in item.ancestors and item.region.overlaps(window.content_region)]
                        assert older_widgets
                        end_widget = older_widgets[0]
                        native = SelectState._walk_selected_widgets
                        native_calls = []

                        def counted(state):
                            native_calls.append(1)
                            return native(state)

                        with patch.object(SelectState, "_walk_selected_widgets", counted):
                            painted = app.next_paint = asyncio.get_running_loop().create_future()
                            started = time.perf_counter()
                            profile_path = os.environ.get("TOAD_OFFSCREEN_PROFILE")
                            drag_profiler = cProfile.Profile() if profile_path else None
                            if drag_profiler is not None:
                                drag_profiler.enable()
                            x, y = end_widget.region.x + 3, end_widget.region.y
                            app.mouse_position = Offset(x, y)
                            app.screen._forward_event(events.MouseMove(None, x, y, 2, -1, 1, False, False, False))
                            drag_ms = (await asyncio.wait_for(painted, 5) - started) * 1000
                            if drag_profiler is not None:
                                drag_profiler.disable()
                                drag_profiler.dump_stats(profile_path)
                            app.next_paint = None
                            app.screen._stop_auto_scroll()
                            await pilot.pause()
                        selected_text = app.screen.get_selected_text() or ""
                        assert native_calls, "Off-screen drag did not use canonical selector"
                        assert start_widget in app.screen.selections
                        assert end_widget in app.screen.selections
                        assert len(selected_text) > 100, "Selection did not span older history"
                        await pilot.mouse_up(end_widget, offset=(3, 0))
                        if drag_ms >= 16:
                            violations.append((target, "offscreen_drag", round(drag_ms, 1)))
                        print(json.dumps({"replies": target,
                                          "offscreen_drag_ms": round(drag_ms, 1),
                                          "native_fallback_calls": len(native_calls),
                                          "copied_characters": len(selected_text)}))
            if age_sweep:
                if os.environ.get("TOAD_BENCH_ENFORCE_16") == "1":
                    assert not violations, f"Frames exceeded 16 ms: {violations}"
            else:
                await measure_baseline(app, pilot, conversation)
        if scroll_profiler is not None:
            scroll_profiler.dump_stats(scroll_profile_path)
        # A fixture's interactive /bin/sh can outlive App.run_test() and keep
        # stdout/stderr open after Python exits, hanging the benchmark runner.
        # Retire only this fixture's direct child in its unique temporary cwd;
        # never touch persistent coordination workers or another Toad process.
        for child in psutil.Process().children():
            try:
                if child.cmdline() != ["/bin/sh"] or Path(child.cwd()) != root:
                    continue
                child.terminate()
                try:
                    await asyncio.to_thread(child.wait, timeout=2)
                except psutil.TimeoutExpired:
                    if child.cmdline() == ["/bin/sh"] and Path(child.cwd()) == root:
                        child.kill()
                        await asyncio.to_thread(child.wait, timeout=2)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        await asyncio.get_running_loop().shutdown_default_executor()


if __name__ == "__main__":
    asyncio.run(main())
