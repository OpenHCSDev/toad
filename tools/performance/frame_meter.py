"""Total UI-thread work per frame and input-to-paint latency in a live Textual app.

``install`` runs inside the application (through ``capture_live.py --frame-meter``).
Every event-loop callback is timed; a frame is the UI-thread work done since the
previous frame was handed to the driver. An input event is timed from the moment
the driver posts it to the App until the first frame handed over after its last
handler returns. ``python frame_meter.py RESULT.json`` prints the series-table numbers.
"""

import bisect
import collections
import json
import os
import statistics
import sys
import threading
import time
from contextlib import contextmanager

# Intervals (monotonic ns) in which a snapshot ran inside the app: the meter
# leaves frames and lags overlapping them out, since the measurement caused them.
PAUSES: list[tuple[int, int]] = []


@contextmanager
def measuring_pause():
    begin = time.monotonic_ns()
    try:
        yield
    finally:
        PAUSES.append((begin, time.monotonic_ns()))


def install(*, expected_pid, seconds, output):
    import asyncio
    import gc
    from asyncio import events as loop_events
    from textual import events
    from textual._context import active_app
    from textual.message_pump import MessagePump
    from textual.widget import Widget

    if os.getpid() != expected_pid:
        raise RuntimeError("Unexpected capture process")
    app = active_app.get(None)
    for task in () if app is not None else asyncio.all_tasks():
        if (app := task.get_context().get(active_app, None)) is not None:
            break
    if app is None:
        raise RuntimeError("No application context")

    inputs_types = (events.Key, events.MouseScrollUp, events.MouseScrollDown)
    clock = time.monotonic_ns
    state = {"busy": 0, "current": None, "parts": {}, "cpu": time.thread_time_ns(), "shown": clock()}
    frames, inputs, slow, slow_frames = [], [], [], []
    run, post, dispatch = loop_events.Handle._run, MessagePump.post_message, MessagePump._dispatch_message
    refresh = Widget.refresh
    layouts = {}
    repaints = {}

    def counted_refresh(self, *regions, repaint=True, layout=False, recompose=False):
        # Each layout request re-arranges the screen; count who asks.
        name = type(self).__name__
        if layout:
            caller = sys._getframe(1)
            while caller is not None and caller.f_code.co_name in ("refresh", "_refresh"):
                caller = caller.f_back
            key = f"{name} <- {caller.f_code.co_qualname if caller else '?'}"
            layouts[key] = layouts.get(key, 0) + 1
        elif repaint:
            # Repaints are cheaper than layouts but each repainted widget
            # renders its lines again; count who asks.
            caller = sys._getframe(1)
            while caller is not None and caller.f_code.co_name in ("refresh", "_refresh"):
                caller = caller.f_back
            key = f"{name} <- {caller.f_code.co_qualname if caller else '?'}"
            repaints[key] = repaints.get(key, 0) + 1
        return refresh(self, *regions, repaint=repaint, layout=layout, recompose=recompose)

    from textual.screen import Screen
    refresh_bindings = Screen.refresh_bindings
    refresh_layout = Screen._refresh_layout

    def timed_layout(self, *args, **kwargs):
        # Whole-screen layout inside a frame: how much of a slow frame it is.
        begin = clock()
        try:
            return refresh_layout(self, *args, **kwargs)
        finally:
            state["layout"] = state.get("layout", 0) + (clock() - begin) / 1e6
            state["layouts"] = state.get("layouts", 0) + 1
    binding_refreshes = {}

    def counted_bindings(self):
        # Every binding refresh rebuilds the footer's binding state; count callers.
        caller = sys._getframe(1)
        if caller.f_code.co_name == "refresh_bindings":
            caller = caller.f_back
        name = f"{caller.f_code.co_qualname} {caller.f_code.co_filename.rsplit('/', 2)[-1]}"
        binding_refreshes[name] = binding_refreshes.get(name, 0) + 1
        return refresh_bindings(self)
    app_type = type(app)
    display = app_type._display

    stalls = {}
    long_callbacks = {}
    main_thread = threading.get_ident()

    def watch_stalls():
        # A sampled profile misses a rare long callback; sample the UI
        # thread's stack while one callback has run past 8 ms.
        while not state.get("finished"):
            time.sleep(0.004)
            begin = state["current"]
            if begin is None or clock() - begin < 8_000_000:
                continue
            frame = sys._current_frames().get(main_thread)
            if frame is None:
                continue
            # Walk frames directly: extract_stack reads source lines (file
            # I/O under the GIL), lengthening the very stall being sampled.
            stack = []
            while frame is not None:
                code = frame.f_code
                if "/src/" in code.co_filename or "site-packages" in code.co_filename:
                    path = code.co_filename.split('/src/')[-1].split('site-packages/')[-1]
                    stack.append(f"{code.co_name} {path}:{frame.f_lineno}")
                frame = frame.f_back
            stack.reverse()
            # Innermost frames show the work; the outermost Toad frames show
            # what started it.
            full = stack
            stack = stack[:8] + ["..."] + stack[-8:] if len(stack) > 16 else stack
            key = " < ".join(reversed(stack))
            stalls[key] = stalls.get(key, 0) + 1
            # Keep each long callback's own samples, by its start, to read one
            # stall in full rather than only the run's aggregate.
            long_callbacks.setdefault(begin, []).append(" < ".join(reversed(full)))

    def timed_run(handle):
        state["current"] = begin = clock()
        # A stall is a stretch the loop could not paint in: callbacks closer
        # than 1 ms together form one stretch.
        if begin - state.get("stretch_end", 0) > 1_000_000:
            state["stretch_begin"] = begin
        try:
            return run(handle)
        finally:
            end = clock()
            state["stretch_end"] = end
            stretch = (end - state["stretch_begin"]) / 1e6
            if stretch > state.get("stall", 0):
                state["stall"] = stretch
            spent = end - begin
            state["busy"] += spent
            state["current"] = None
            if spent > 20_000:
                callback = handle._callback
                owner = getattr(callback, "__self__", None)
                if isinstance(owner, asyncio.Task):
                    coroutine = owner.get_coro()
                    callback = getattr(coroutine, "__qualname__", None) or repr(coroutine)[:80]
                    frame = getattr(coroutine, "cr_frame", None)
                    target = frame.f_locals.get("self") if frame is not None else None
                    if target is not None:
                        work = getattr(target, "_work", None)
                        work = getattr(work, "func", work)
                        label = (getattr(work, "__qualname__", None) or getattr(target, "_name", None)
                                 or getattr(target, "name", None))
                        callback += f" [{type(target).__name__}{':' + str(label)[:40] if label else ''}]"
                else:
                    callback = getattr(callback, "__qualname__", None) or repr(callback)[:80]
                # Callbacks are totalled per owner within a frame: a slow
                # frame is usually many small callbacks, not one long one.
                parts = state["parts"]
                parts[callback] = parts.get(callback, 0) + spent / 1e6
                counts = state.setdefault("counts", {})
                counts[callback] = counts.get(callback, 0) + 1

    def collected(phase, info):
        # Collector pauses land inside whichever callback allocated; record
        # them separately so they are not blamed on that owner.
        if phase == "start":
            state["gc"] = clock()
        elif (began := state.pop("gc", None)) is not None:
            parts = state["parts"]
            label = f"gc generation {info['generation']}"
            parts[label] = parts.get(label, 0) + (clock() - began) / 1e6

    def timed_display(self, screen, renderable):
        result = display(self, screen, renderable)
        if renderable is not None and self is app:
            now = clock()
            running = 0 if state["current"] is None else now - state["current"]
            work = (state["busy"] + running) / 1e6
            cpu = time.thread_time_ns()
            frames.append((now, work, state.get("stall", 0)))
            # A paint ends the stretch: the next one starts after it.
            state["stall"] = 0
            state["stretch_begin"] = state["stretch_end"] = now
            if work > 16:
                # UI-thread CPU over the same interval: far below the work
                # means the loop was waiting for the GIL, not computing.
                counts = state.get("counts", {})
                parts = [(label, ms, counts.get(label, 0))
                         for label, ms in sorted(state["parts"].items(), key=lambda part: -part[1])]
                slow_frames.append((now, work, parts, (cpu - state["cpu"]) / 1e6, (now - state["shown"]) / 1e6,
                                    state.get("layout", 0), state.get("layouts", 0)))
            state["parts"] = {}
            state["counts"] = {}
            state["cpu"], state["shown"] = cpu, now
            state["layout"] = state["layouts"] = 0
            # The running callback adds its full duration when it returns;
            # the part already counted in this frame is subtracted here.
            state["busy"] = -running
        return result

    def timed_post(self, message):
        # The record travels with the message: ids are reused once objects die.
        if self is app and isinstance(message, inputs_types) and "_frame_meter" not in vars(message):
            message._frame_meter = entry = [clock(), None, type(message).__name__, []]
            inputs.append(entry)
        return post(self, message)

    async def timed_dispatch(self, message):
        begin = clock()
        try:
            return await dispatch(self, message)
        finally:
            end = clock()
            if (entry := vars(message).get("_frame_meter")) is not None:
                entry[1] = end
                entry[3].append((type(self).__name__, begin, end))
            if end - begin > 50_000_000:
                slow.append((begin, (end - begin) / 1e6, type(self).__name__, type(message).__qualname__,
                             type(getattr(message, "event", None)).__qualname__))

    def finish():
        state["finished"] = True
        Widget.refresh = refresh
        Screen.refresh_bindings = refresh_bindings
        Screen._refresh_layout = refresh_layout
        gc.callbacks.remove(collected)
        loop_events.Handle._run = run
        MessagePump.post_message = post
        MessagePump._dispatch_message = dispatch
        app_type._display = display
        # Readers wait for the file to appear: publish it complete, by rename.
        partial = output + ".partial"
        fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as file:
            json.dump({"pid": expected_pid, "seconds": seconds,
                       "frames": frames, "inputs": inputs, "lags": lags, "pauses": PAUSES,
                       "long_callbacks": sorted(long_callbacks.items()),
                       "slow_handlers": slow, "slow_frames": slow_frames,
                       "layout_requests": layouts, "repaint_requests": repaints,
                       "binding_refreshes": binding_refreshes,
                       "stalls": sorted(stalls.items(), key=lambda item: -item[1])[:40],
                       "gc": {"tracked": len(gc.get_objects()), "frozen": gc.get_freeze_count(),
                              "stats": gc.get_stats(), "threshold": gc.get_threshold()}}, file)
        os.rename(partial, output)

    # Event-loop lag: how late a callback due every 4 ms actually ran is how
    # long an input or a paint arriving then would have waited.
    loop = asyncio.get_running_loop()
    lags = []

    def probe(due):
        now = loop.time()
        lags.append((clock(), round((now - due) * 1000, 2)))
        if not state.get("finished"):
            loop.call_at(now + 0.004, probe, now + 0.004)

    loop.call_at(loop.time() + 0.004, probe, loop.time() + 0.004)
    gc.callbacks.append(collected)
    threading.Thread(target=watch_stalls, name="frame-meter-stalls", daemon=True).start()
    Widget.refresh = counted_refresh
    Screen.refresh_bindings = counted_bindings
    Screen._refresh_layout = timed_layout
    loop_events.Handle._run = timed_run
    MessagePump.post_message = timed_post
    MessagePump._dispatch_message = timed_dispatch
    app_type._display = timed_display
    asyncio.get_running_loop().call_later(seconds, finish)


def targets(*, expected_pid, output):
    """Write where sidebar thread rows and session tabs are, in screen cells."""
    with measuring_pause():
        _targets(expected_pid=expected_pid, output=output)


def _targets(*, expected_pid, output):
    import asyncio
    from textual._context import active_app

    if os.getpid() != expected_pid:
        raise RuntimeError("Unexpected capture process")
    app = active_app.get(None)
    for task in () if app is not None else asyncio.all_tasks():
        if (app := task.get_context().get(active_app, None)) is not None:
            break
    from toad.widgets.history_anchor import HistoryWindow

    screen = app.screen
    # Only on-screen rows and tabs can be clicked; reading an off-screen
    # widget's region would make the app reflow its viewport.
    shown = screen._compositor.visible_widgets
    rows = {row.target_name: tuple(shown[row][0]) for row in screen.query("ThreadRow") if row in shown}
    tabs = [tuple(shown[tab][0]) for tab in screen.query("SessionLabel") if tab in shown]
    # What the screen actually shows, row by row, and the visible message
    # window: the scenario checks blank runs, placeholders, End and tab return
    # from this text rather than from screenshots.
    compositor = screen._compositor
    text = [strip.text for strip in compositor.render_strips()]
    visible = compositor.visible_widgets
    window = next((node for node in screen.query(HistoryWindow) if node in visible), None)
    message_window = None
    if window is not None:
        region = window.scrollable_content_region
        message_window = {"region": tuple(region), "scroll_y": window.scroll_y,
                          "max_scroll_y": window.max_scroll_y, "follows_tail": window.follows_tail}
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as file:
        arranged = {}
        for node in compositor._layout_map:
            arranged[type(node).__name__] = arranged.get(type(node).__name__, 0) + 1
        # What each open tab keeps warm, as the retention budget counts it.
        retained = [{"screen": screen_.id, "widgets": owner.retained_widget_count,
                     "source_bytes": owner.retained_source_bytes, "paint_bytes": owner.retained_paint_bytes}
                    for screen_, owner in app.workspace_chrome.native._presentations()]
        # Everything the current conversation mounted, shown or not, by type.
        mounted = collections.Counter(
            type(node).__name__ for view in app.workspace_sessions.views.values()
            if (owner := getattr(view, "presentation", None)) is not None and owner.widget is not None
            for node in owner.widget.walk_children(with_self=True))
        json.dump({"threads": rows, "tabs": tabs, "text": text, "message_window": message_window,
                   "arranged": arranged, "retained": retained, "mounted": dict(mounted.most_common())}, file)


def profile_layout(*, expected_pid, output, calls=40, target="textual.screen:Screen._refresh_layout"):
    """Deterministically profile the next calls of ``target`` (sync) and write the top costs.

    cProfile in Python 3.12+ instruments every thread, so background threads'
    work in the same window appears too; read callers before trusting a line.
    """
    import cProfile
    import importlib
    import inspect
    import pstats
    import io

    if os.getpid() != expected_pid:
        raise RuntimeError("Unexpected capture process")
    module_name, _, path = target.partition(":")
    Screen = importlib.import_module(module_name)
    *parents, method = path.split(".")
    for parent in parents:
        Screen = getattr(Screen, parent)
    original = getattr(Screen, method)
    profiler = cProfile.Profile()
    seen = {"calls": 0}

    def write():
        if seen["calls"] == calls:
            setattr(Screen, method, original)
        text = io.StringIO()
        stats = pstats.Stats(profiler, stream=text)
        stats.sort_stats("cumulative").print_stats(45)
        stats.sort_stats("tottime").print_stats(30)
        # Comms reads must not run inside a layout: show who calls them.
        stats.print_callers("locked_store|store_files|registration|history_views")
        # Restyling a subtree and mounting are the costs of building a view: who asks.
        stats.print_callers("dom.py.*(add_class|remove_class|set_class)|widget.py.*\\(mount\\)|update_node_styles")
        partial = output + ".partial"
        with open(partial, "w") as file:
            file.write(text.getvalue())
        os.rename(partial, output)

    if inspect.iscoroutinefunction(original):
        async def profiled(self, *args, **kwargs):
            if seen["calls"] >= calls:
                return await original(self, *args, **kwargs)
            seen["calls"] += 1
            profiler.enable()
            try:
                return await original(self, *args, **kwargs)
            finally:
                profiler.disable()
                # Cumulative so far: a run with fewer calls still reports.
                write()
    else:
        def profiled(self, *args, **kwargs):
            if seen["calls"] >= calls:
                return original(self, *args, **kwargs)
            seen["calls"] += 1
            profiler.enable()
            try:
                return original(self, *args, **kwargs)
            finally:
                profiler.disable()
                # Cumulative so far: a run with fewer calls still reports.
                write()

    setattr(Screen, method, profiled)


def _subject(args) -> str:
    """Which object a traced call was for (its type and id), and who called it."""
    caller, chain = sys._getframe(2), []
    while caller is not None and len(chain) < 8:
        chain.append(f"{caller.f_code.co_qualname}:{caller.f_lineno}")
        caller = caller.f_back
    subjects = " ".join(f"{type(subject).__name__}#{getattr(subject, 'id', None) or ''}" for subject in args[:2])
    return f"{subjects} <- {' < '.join(chain)}"


def trace_calls(*, expected_pid, output, targets, seconds=60):
    """Time each call of the named methods ("module:Class.method", sync or async)."""
    import asyncio
    import functools
    import importlib
    import inspect

    if os.getpid() != expected_pid:
        raise RuntimeError("Unexpected capture process")
    calls, restore = [], []
    for target in targets:
        module_name, _, path = target.partition(":")
        owner = importlib.import_module(module_name)
        *parents, name = path.split(".")
        for parent in parents:
            owner = getattr(owner, parent)
        original = getattr(owner, name)
        if inspect.iscoroutinefunction(original):
            @functools.wraps(original)
            async def timed(*args, __original=original, __target=target, **kwargs):
                begin = time.monotonic_ns()
                try:
                    return await __original(*args, **kwargs)
                finally:
                    calls.append((__target, (time.monotonic_ns() - begin) / 1e6, _subject(args)))
        else:
            @functools.wraps(original)
            def timed(*args, __original=original, __target=target, **kwargs):
                begin = time.monotonic_ns()
                try:
                    return __original(*args, **kwargs)
                finally:
                    calls.append((__target, (time.monotonic_ns() - begin) / 1e6, _subject(args)))
        setattr(owner, name, timed)
        restore.append((owner, name, original))

    def finish():
        for owner, name, original in restore:
            setattr(owner, name, original)
        partial = output + ".partial"
        with open(partial, "w") as file:
            json.dump(calls, file)
        os.rename(partial, output)

    asyncio.get_running_loop().call_later(seconds, finish)


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))] if ordered else float("nan")


def summarize(path):
    data = json.load(open(path))
    # Leave out what the scenario's own snapshots caused: a frame whose
    # interval, or a lag whose wait, overlaps a snapshot (5 ms either side).
    pauses = [(begin - 5_000_000, end + 5_000_000) for begin, end in data.get("pauses", [])]

    def measured(begin, end):
        return not any(begin < pause_end and pause_begin < end for pause_begin, pause_end in pauses)

    frames = [frame for previous, frame in zip([None, *data["frames"]], data["frames"])
              if measured(previous[0] if previous else frame[0], frame[0])]
    data["lags"] = [(at, lag) for at, lag in data.get("lags", []) if measured(at - lag * 1e6, at)]
    data["inputs"] = [entry for entry in data["inputs"] if measured(entry[0], entry[1] or entry[0])]
    work = [frame[1] for frame in frames]
    # The longest stretch per frame the loop could not paint in (older
    # captures lack it: their frame work is the only measure).
    stalls = [frame[2] if len(frame) > 2 else frame[1] for frame in frames]
    ends = [frame[0] for frame in frames]
    latencies = []
    for arrived, handled, *_ in data["inputs"]:
        if handled is not None and (position := bisect.bisect_left(ends, handled)) < len(ends):
            latencies.append((ends[position] - arrived) / 1e6)
    return {
        "snapshot_pauses": len(pauses), "frames_left_out": len(data["frames"]) - len(frames),
        "frames": len(work), "inputs": len(data["inputs"]), "painted_inputs": len(latencies),
        "frame_median_ms": round(statistics.median(work), 1) if work else None,
        "frame_p95_ms": round(percentile(work, .95), 1),
        "frame_p99_ms": round(percentile(work, .99), 1),
        "input_to_paint_median_ms": round(statistics.median(latencies), 1) if latencies else None,
        "input_to_paint_p95_ms": round(percentile(latencies, .95), 1),
        "input_to_paint_p99_ms": round(percentile(latencies, .99), 1),
        "frame_worst_ms": round(max(work), 1) if work else None,
        "frames_over_16_33_50": [sum(value > limit for value in work) for limit in (16, 33, 50)],
        "stall_p95_ms": round(percentile(stalls, .95), 1),
        "stall_worst_ms": round(max(stalls), 1) if stalls else None,
        "stalls_over_16_33_50": [sum(value > limit for value in stalls) for limit in (16, 33, 50)],
        **lag_summary(data.get("lags", [])),
    }


def lag_summary(lags):
    """How long input or paint would have waited: the loop's lateness."""
    if not lags:
        return {}
    late = [lag for _at, lag in lags]
    return {"lag_p95_ms": round(percentile(late, .95), 1), "lag_p99_ms": round(percentile(late, .99), 1),
            "lag_worst_ms": round(max(late), 1),
            "lags_over_16_33_50": [sum(value > limit for value in late) for limit in (16, 33, 50)]}


if __name__ == "__main__":
    print(json.dumps(summarize(sys.argv[1]), indent=2))
