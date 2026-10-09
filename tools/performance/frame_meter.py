"""Total UI-thread work per frame and input-to-paint latency in a live Textual app.

``install`` runs inside the application (through ``capture_live.py --frame-meter``).
Every event-loop callback is timed; a frame is the UI-thread work done since the
previous frame was handed to the driver. An input event is timed from the moment
the driver posts it to the App until the first frame handed over after its last
handler returns. ``python frame_meter.py RESULT.json`` prints the series-table numbers.
"""

import bisect
import json
import os
import statistics
import sys
import threading
import time
import traceback


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
            stack = [f"{f.name} {f.filename.split('/src/')[-1].split('site-packages/')[-1]}:{f.lineno}"
                     for f in traceback.extract_stack(frame)
                     if "/src/" in f.filename or "site-packages" in f.filename]
            # Innermost frames show the work; the outermost Toad frames show
            # what started it.
            stack = stack[:8] + ["..."] + stack[-8:] if len(stack) > 16 else stack
            key = " < ".join(reversed(stack))
            stalls[key] = stalls.get(key, 0) + 1

    def timed_run(handle):
        state["current"] = begin = clock()
        try:
            return run(handle)
        finally:
            spent = clock() - begin
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
            frames.append((now, work))
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
                       "frames": frames, "inputs": inputs,
                       "slow_handlers": slow, "slow_frames": slow_frames,
                       "layout_requests": layouts, "repaint_requests": repaints,
                       "binding_refreshes": binding_refreshes,
                       "stalls": sorted(stalls.items(), key=lambda item: -item[1])[:40],
                       "gc": {"tracked": len(gc.get_objects()), "frozen": gc.get_freeze_count(),
                              "stats": gc.get_stats(), "threshold": gc.get_threshold()}}, file)
        os.rename(partial, output)

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
    rows = {row.target_name: tuple(row.region) for row in screen.query("ThreadRow") if row.region}
    tabs = [tuple(tab.region) for tab in screen.query("SessionLabel") if tab.region]
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
        json.dump({"threads": rows, "tabs": tabs, "text": text, "message_window": message_window,
                   "arranged": arranged}, file)


def profile_layout(*, expected_pid, output, calls=40):
    """Deterministically profile the next screen layouts and write the top costs."""
    import cProfile
    import pstats
    import io
    from textual.screen import Screen

    if os.getpid() != expected_pid:
        raise RuntimeError("Unexpected capture process")
    original = Screen._refresh_layout
    profiler = cProfile.Profile()
    seen = {"calls": 0}

    def profiled(self, *args, **kwargs):
        if seen["calls"] >= calls:
            return original(self, *args, **kwargs)
        seen["calls"] += 1
        profiler.enable()
        try:
            return original(self, *args, **kwargs)
        finally:
            profiler.disable()
            if seen["calls"] == calls:
                Screen._refresh_layout = original
                text = io.StringIO()
                stats = pstats.Stats(profiler, stream=text)
                stats.sort_stats("cumulative").print_stats(45)
                stats.sort_stats("tottime").print_stats(30)
                # Comms reads must not run inside a layout: show who calls them.
                stats.print_callers("locked_store|store_files|registration|history_views")
                partial = output + ".partial"
                with open(partial, "w") as file:
                    file.write(text.getvalue())
                os.rename(partial, output)

    Screen._refresh_layout = profiled


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))] if ordered else float("nan")


def summarize(path):
    data = json.load(open(path))
    frames = data["frames"]
    work = [busy for _end, busy in frames]
    ends = [end for end, _busy in frames]
    latencies = []
    for arrived, handled, *_ in data["inputs"]:
        if handled is not None and (position := bisect.bisect_left(ends, handled)) < len(ends):
            latencies.append((ends[position] - arrived) / 1e6)
    return {
        "frames": len(work), "inputs": len(data["inputs"]), "painted_inputs": len(latencies),
        "frame_median_ms": round(statistics.median(work), 1) if work else None,
        "frame_p95_ms": round(percentile(work, .95), 1),
        "frame_p99_ms": round(percentile(work, .99), 1),
        "input_to_paint_median_ms": round(statistics.median(latencies), 1) if latencies else None,
        "input_to_paint_p95_ms": round(percentile(latencies, .95), 1),
        "input_to_paint_p99_ms": round(percentile(latencies, .99), 1),
    }


if __name__ == "__main__":
    print(json.dumps(summarize(sys.argv[1]), indent=2))
