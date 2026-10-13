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


def _running_app(expected_pid):
    """The application running in this process (remote code runs outside its context)."""
    import asyncio
    from textual._context import active_app

    if os.getpid() != expected_pid:
        raise RuntimeError("Unexpected capture process")
    app = active_app.get(None)
    if app is None:
        from asyncio.tasks import _eager_tasks, _scheduled_tasks
        tasks = (*tuple(_scheduled_tasks), *tuple(_eager_tasks))
    else:
        tasks = ()
    for task in tasks:
        if (app := task.get_context().get(active_app, None)) is not None:
            break
    if app is None:
        raise RuntimeError("No application context")
    return app


def install(*, expected_pid, seconds, output):
    import asyncio
    import gc
    from asyncio import events as loop_events
    from textual import events
    from textual.message_pump import MessagePump
    from textual.widget import Widget

    app = _running_app(expected_pid)

    inputs_types = (events.Key, events.MouseScrollUp, events.MouseScrollDown)
    clock = time.monotonic_ns
    state = {"busy": 0, "current": None, "parts": {}, "cpu": time.thread_time_ns(), "shown": clock()}
    frames, inputs, slow, slow_frames, gc_pauses = [], [], [], [], []
    switch_steps = []
    # Each layout that ran in more than one step or had a step over 4 ms
    # (Screen._layout_step): its start, step budget and every step's length.
    stepped_layouts = []
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

    # Builds before the screen's own layouts ran in steps have no steps to time.
    layout_step = getattr(Screen, "_layout_step", None)
    # The layout each running step generator belongs to, until its last step.
    running_layouts = {}

    def traced_layout_step(self, steps, deadline, step_ns):
        begin, last = clock(), True
        try:
            last = layout_step(self, steps, deadline, step_ns)
            return last
        finally:
            record = running_layouts.setdefault(id(steps), (begin, step_ns, []))
            record[2].append((clock() - begin) / 1e6)
            if last:
                del running_layouts[id(steps)]
                if len(record[2]) > 1 or record[2][0] > 4:
                    stepped_layouts.append(record)

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
    # Per long callback: the other threads' innermost frames in the same
    # samples. When the UI thread waited for the GIL, the holder's frame
    # still points at the call that held it when this watcher gets the GIL.
    stall_threads = {}
    timed_callbacks = []
    # Every callback since the lag probe last ran, and, per wait over 12 ms,
    # the callbacks that made it up: a wait is often one loop turn of many
    # short callbacks, none long enough to be recorded on its own.
    since_probe, long_waits = [], []
    main_thread = threading.get_ident()

    def watch_stalls():
        # A sampled profile misses a rare long callback; sample the UI
        # thread's stack while one callback has run past 8 ms.
        while not state.get("finished"):
            time.sleep(0.004)
            begin = state["current"]
            if begin is None or clock() - begin < 8_000_000:
                continue
            frames_now = sys._current_frames()
            frame = frames_now.get(main_thread)
            if frame is None:
                continue
            others = {}
            for ident, other in frames_now.items():
                if ident in (main_thread, threading.get_ident()):
                    continue
                if other.f_code.co_name in ("wait", "_worker", "select", "get", "_wait_for_tstate_lock"):
                    continue  # idle
                chain = []
                while other is not None and len(chain) < 8:
                    chain.append(f"{other.f_code.co_name} {other.f_code.co_filename.rsplit('/', 2)[-1]}:{other.f_lineno}")
                    other = other.f_back
                others[threading._active.get(ident).name if ident in threading._active else str(ident)] = " < ".join(chain)
            if others:
                stall_threads.setdefault(begin, []).append(others)
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
        cpu_begin = time.thread_time_ns()
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
                if callback.startswith("ToadApp._switch_mode_ready"):
                    # Every loop turn of a tab switch, whatever its length.
                    switch_steps.append((begin, spent / 1e6))
                if spent > 8_000_000:
                    # Each long callback's exact duration, owner and UI-thread
                    # CPU (far below the duration: the thread was waiting for
                    # the GIL or a CPU); its stall samples (same start) show
                    # where the time went.
                    timed_callbacks.append((begin, spent / 1e6, callback, (time.thread_time_ns() - cpu_begin) / 1e6))
                # Callbacks are totalled per owner within a frame: a slow
                # frame is usually many small callbacks, not one long one.
                since_probe.append((begin, spent / 1e6, callback))
                parts = state["parts"]
                parts[callback] = parts.get(callback, 0) + spent / 1e6
                counts = state.setdefault("counts", {})
                counts[callback] = counts.get(callback, 0) + 1

    def collected(phase, info):
        # Collector pauses land inside whichever callback allocated; record
        # them separately so they are not blamed on that owner.
        if phase == "start":
            state["gc"] = clock()
            # Objects allocated since the last collection that did any work:
            # a collection that waited long has that many young objects to scan.
            state["gc_young"] = gc.get_count()[0]
        elif (began := state.pop("gc", None)) is not None:
            parts = state["parts"]
            label = f"gc generation {info['generation']}"
            spent = (clock() - began) / 1e6
            parts[label] = parts.get(label, 0) + spent
            gc_pauses.append((began, spent, info["generation"], info["collected"], info["uncollectable"],
                              state.pop("gc_young", 0)))

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
            if end - begin > 200_000:
                # Inside its pump's callback: which message the time went to.
                since_probe.append((begin, (end - begin) / 1e6,
                                    f"  message {type(message).__name__} to {type(self).__name__}"))
            if end - begin > 50_000_000:
                slow.append((begin, (end - begin) / 1e6, type(self).__name__, type(message).__qualname__,
                             type(getattr(message, "event", None)).__qualname__))

    def finish():
        state["finished"] = True
        Widget.refresh = refresh
        Screen.refresh_bindings = refresh_bindings
        Screen._refresh_layout = refresh_layout
        if layout_step is not None:
            Screen._layout_step = layout_step
        # Layouts replaced before their last step.
        stepped_layouts.extend(running_layouts.values())
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
                       "stall_threads": sorted(stall_threads.items()),
                       # Kernel thread id to Python thread name, to name the
                       # per-thread CPU sampler's rows (a thread the kernel
                       # still calls by the process name is one of these).
                       "threads": sorted((thread.native_id, thread.name) for thread in threading.enumerate()),
                       "timed_callbacks": timed_callbacks, "long_waits": long_waits, "switch_steps": switch_steps,
                       "stepped_layouts": stepped_layouts,
                       "slow_handlers": slow, "slow_frames": slow_frames,
                       "layout_requests": layouts, "repaint_requests": repaints,
                       "binding_refreshes": binding_refreshes,
                       "stalls": sorted(stalls.items(), key=lambda item: -item[1])[:40],
                       "gc": {"tracked": len(gc.get_objects()), "frozen": gc.get_freeze_count(),
                              # What the collector still scans (frozen objects excluded), by type.
                              "tracked_types": collections.Counter(
                                  f"{type(item).__module__}.{type(item).__qualname__}"
                                  for item in gc.get_objects()).most_common(40),
                              "stats": gc.get_stats(), "threshold": gc.get_threshold(),
                              "pauses": gc_pauses}}, file)
        os.rename(partial, output)

    # Event-loop lag: how late a callback due every 4 ms actually ran is how
    # long an input or a paint arriving then would have waited.
    loop = asyncio.get_running_loop()
    lags = []

    def probe(due):
        now = loop.time()
        lags.append((clock(), round((now - due) * 1000, 2)))
        if now - due > 0.012:
            # From 12 ms, so the turns just under the 16 ms target are seen too.
            long_waits.append((clock(), round((now - due) * 1000, 2), list(since_probe)))
        since_probe.clear()
        if not state.get("finished"):
            loop.call_at(now + 0.004, probe, now + 0.004)

    loop.call_at(loop.time() + 0.004, probe, loop.time() + 0.004)
    gc.callbacks.append(collected)
    threading.Thread(target=watch_stalls, name="frame-meter-stalls", daemon=True).start()
    Widget.refresh = counted_refresh
    Screen.refresh_bindings = counted_bindings
    Screen._refresh_layout = timed_layout
    if layout_step is not None:
        Screen._layout_step = traced_layout_step
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
    app = _running_app(expected_pid)
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
        # The raw statistics, for reading callers offline with pstats.
        profiler.dump_stats(output + ".prof")
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


def profile_within(*, expected_pid, output, target, within, calls=3, min_ms=0.0):
    """Profile each call of ``target`` (sync) made while a ``within`` call runs.

    One statistics file per ``within`` call (output.N.prof). With ``min_ms``,
    a ``within`` call is kept only when one of its profiled ``target`` calls
    took at least that long (profiled time), so N counts only slow calls. cProfile sees every
    thread, so while a target call runs the GIL switch interval is raised to
    one second: the target is synchronous Python, so no other thread runs
    inside it and the statistics are the UI thread's alone.
    """
    import cProfile
    import gc
    import importlib
    import inspect

    if os.getpid() != expected_pid:
        raise RuntimeError("Unexpected capture process")

    def resolve(path):
        module_name, _, attribute = path.partition(":")
        owner = importlib.import_module(module_name)
        *parents, method = attribute.split(".")
        for parent in parents:
            owner = getattr(owner, parent)
        return owner, method, getattr(owner, method)

    target_owner, target_name, target_original = resolve(target)
    within_owner, within_name, within_original = resolve(within)
    state = {"current": None, "count": 0, "longest": 0.0, "kept": []}

    def profiled(*args, **kwargs):
        profiler = state["current"]
        if profiler is None:
            return target_original(*args, **kwargs)
        interval = sys.getswitchinterval()
        sys.setswitchinterval(1.0)
        # A collection inside the call is charged to whichever function it
        # interrupts; collection pauses are measured by the frame meter.
        collecting = gc.isenabled()
        gc.disable()
        begin = time.perf_counter()
        try:
            return profiler.runcall(target_original, *args, **kwargs)
        finally:
            state["longest"] = max(state["longest"], (time.perf_counter() - begin) * 1e3)
            if collecting:
                gc.enable()
            sys.setswitchinterval(interval)

    def finish(profiler):
        state["current"] = None
        longest, state["longest"] = state["longest"], 0.0
        if longest < min_ms or (min_ms and not longest):
            return
        state["kept"].append((longest, time.monotonic_ns()))
        state["count"] += 1
        profiler.dump_stats(f"{output}.{state['count']}.prof")
        if state["count"] >= calls:
            setattr(target_owner, target_name, target_original)
            setattr(within_owner, within_name, within_original)
            with open(output, "w") as file:
                json.dump({"profiles": state["count"], "profiled_ms": state["kept"]}, file)

    if inspect.iscoroutinefunction(within_original):
        async def scope(*args, **kwargs):
            if state["count"] >= calls:
                return await within_original(*args, **kwargs)
            profiler = state["current"] = cProfile.Profile()
            try:
                return await within_original(*args, **kwargs)
            finally:
                finish(profiler)
    else:
        def scope(*args, **kwargs):
            if state["count"] >= calls:
                return within_original(*args, **kwargs)
            profiler = state["current"] = cProfile.Profile()
            try:
                return within_original(*args, **kwargs)
            finally:
                finish(profiler)

    setattr(target_owner, target_name, profiled)
    setattr(within_owner, within_name, scope)


def profile_slow(*, expected_pid, output, target, calls=3, min_ms=0.0):
    """Profile every call of ``target`` (sync); keep each one that took ``min_ms`` or longer.

    One statistics file per kept call (output.N.prof), at most ``calls``. For
    a target with no patchable enclosing call (the screen's update timer holds
    a bound method, so ``profile_within`` cannot scope its layout). Other
    threads are kept off the GIL during each call, as in ``profile_within``.
    """
    import cProfile
    import gc
    import importlib

    if os.getpid() != expected_pid:
        raise RuntimeError("Unexpected capture process")
    module_name, _, attribute = target.partition(":")
    owner = importlib.import_module(module_name)
    *parents, name = attribute.split(".")
    for parent in parents:
        owner = getattr(owner, parent)
    original = getattr(owner, name)
    kept = []
    running = []

    def profiled(*args, **kwargs):
        if running:
            # A nested call (arrange measures by arranging) is part of the outer profile.
            return original(*args, **kwargs)
        running.append(True)
        try:
            return profile_call(*args, **kwargs)
        finally:
            running.pop()

    def profile_call(*args, **kwargs):
        profiler = cProfile.Profile()
        interval = sys.getswitchinterval()
        sys.setswitchinterval(1.0)
        collecting = gc.isenabled()
        gc.disable()
        begin = time.perf_counter()
        try:
            return profiler.runcall(original, *args, **kwargs)
        finally:
            spent = (time.perf_counter() - begin) * 1e3
            if collecting:
                gc.enable()
            sys.setswitchinterval(interval)
            if spent >= min_ms and len(kept) < calls:
                kept.append((spent, time.monotonic_ns()))
                profiler.dump_stats(f"{output}.{len(kept)}.prof")
                if len(kept) == calls:
                    setattr(owner, name, original)
                    with open(output, "w") as file:
                        json.dump({"profiles": len(kept), "profiled_ms": kept}, file)

    setattr(owner, name, profiled)


def remeasure(*, expected_pid, output, iterations=60):
    """Arrange the live screen at widths it was never laid out at, repeatedly.

    This is the layout work of the first tab switch after the content width
    changes: every widget of the selected tab measured and placed at a new
    width. Each pass arranges the whole screen at a different width (40
    widths in turn, more than a widget's 16 retained measurements), in its
    own loop turn with the collector off, and publishes nothing. The median
    is a per-build figure for the real widget tree, free of the switch's
    other work and of collector pauses. A second set of passes is profiled
    with other threads kept off the GIL, for call counts.

    Measurement caches gain entries for widths the screen is not shown at,
    and transcript pages re-wrap at them: run this after the scenario's checks.
    """
    import asyncio
    import contextvars
    import cProfile
    import gc
    from textual._context import active_app
    from textual.geometry import Size

    app = _running_app(expected_pid)
    # Remote code runs outside the app's context; measurement reads it.
    context = contextvars.copy_context()
    context.run(active_app.set, app)
    screen = app.screen
    width, height = app.size
    passes: list[tuple[int, float, float]] = []
    profiler = cProfile.Profile()
    loop = asyncio.get_running_loop()

    def arrange(index: int, profiled: bool) -> None:
        size = Size(width - 5 - index % 40, height)
        enabled = gc.isenabled()
        gc.disable()
        interval = sys.getswitchinterval()
        if profiled:
            sys.setswitchinterval(1.0)
            profiler.enable()
        begin, cpu = time.perf_counter_ns(), time.thread_time_ns()
        try:
            screen._compositor._arrange_root(screen, size)
        finally:
            spent, spent_cpu = time.perf_counter_ns() - begin, time.thread_time_ns() - cpu
            if profiled:
                profiler.disable()
                sys.setswitchinterval(interval)
            if enabled:
                gc.enable()
        if not profiled:
            passes.append((size.width, spent / 1e6, spent_cpu / 1e6))

    def step(index: int) -> None:
        if index < 2 * iterations:
            # Timed passes first, then the same widths again profiled.
            try:
                arrange(index % iterations, profiled=index >= iterations)
            except Exception:
                # A loop callback's exception is only logged inside the app:
                # write it where the capture waits for the result.
                import traceback
                with open(output, "w") as file:
                    json.dump({"error": traceback.format_exc()}, file)
                raise
            loop.call_later(0.01, step, index + 1, context=context)
            return
        profiler.dump_stats(output + ".prof")
        times = sorted(ms for _width, ms, _cpu in passes)
        partial = output + ".partial"
        with open(partial, "w") as file:
            json.dump({"passes": passes, "median_ms": statistics.median(times),
                       "p10_ms": times[len(times) // 10], "p90_ms": times[len(times) * 9 // 10],
                       "unit_costs": costs, "profiled_passes": iterations}, file)
        os.rename(partial, output)

    def unit_costs() -> dict[str, float]:
        # Per-operation costs in this process, to compare with a fresh one:
        # the deepest widget's parent walk and two attribute reads.
        deepest = max(screen.walk_children(), key=lambda widget: len(tuple(widget.walk_ancestors())))
        costs = {"depth": len(tuple(deepest.walk_ancestors()))}
        for label, operation in (("walk_ancestors_ns", lambda: tuple(deepest.walk_ancestors())),
                                 ("parent_ns", lambda: deepest._parent),
                                 ("styles_height_ns", lambda: deepest.styles.height)):
            begin = time.perf_counter_ns()
            for _ in range(2000):
                operation()
            costs[label] = (time.perf_counter_ns() - begin) / 2000
        return costs

    costs = context.run(unit_costs)
    loop.call_soon(step, 0, context=context)


def repaint(*, expected_pid, output, iterations=40):
    """Repaint the live history viewport in full, repeatedly, and time each paint.

    The paint of a PageUp into history not shown before: every widget drawn
    inside the history window renders its lines again (their styled-line
    caches are cleared) and the window's whole viewport is damaged, then the
    screen publishes it through the real driver. "warm" passes damage the
    same viewport without clearing the line caches (the paint of rows shown
    before). "scroll" passes move the window a page up, then back down, and
    run the screen update the update timer would run (layout, then paint):
    a PageUp's frame within history already loaded. Each pass runs in its own
    loop turn with the collector off; then cold and scroll passes again,
    profiled with other threads kept off the GIL (repaint.json.prof holds
    the cold ones, repaint.json.scroll.prof the scroll ones).
    Run after the scenario's checks: the passes write to the terminal.
    """
    import asyncio
    import contextvars
    import cProfile
    import gc
    from textual._compositor import ChopsUpdate, Compositor
    from textual._context import active_app
    from toad.widgets.history_anchor import HistoryWindow

    app = _running_app(expected_pid)
    context = contextvars.copy_context()
    context.run(active_app.set, app)
    screen = app.screen
    compositor = screen._compositor
    windows = [window for window in screen.query(HistoryWindow) if window in compositor.visible_widgets]
    if len(windows) != 1:
        raise RuntimeError(f"Expected one visible history window, found {len(windows)}")
    window = windows[0]
    passes: list[dict] = []
    profilers = {"cold": cProfile.Profile(), "scroll": cProfile.Profile()}
    loop = asyncio.get_running_loop()
    parts: dict[str, float] = {}
    described: list[dict] = []
    from textual.screen import Screen

    def timed_part(name, original):
        def timed(*args, **kwargs):
            begin = time.perf_counter_ns()
            try:
                return original(*args, **kwargs)
            finally:
                parts[name] = parts.get(name, 0.0) + (time.perf_counter_ns() - begin) / 1e6
        return timed

    def paint(kind: str, profiled: bool, index: int) -> None:
        clip = compositor.visible_widgets[window][1]
        drawn = [widget for widget, (_region, widget_clip) in compositor.visible_widgets.items()
                 if widget_clip.overlaps(clip) and (widget is window or window in widget.ancestors)]
        if kind == "cold":
            for widget in drawn:
                widget._styles_cache.clear()
        if kind == "scroll":
            # Up a page on even passes, back down on odd ones: loaded history.
            page = window.scrollable_content_region.height
            window.scroll_to(y=window.scroll_y + (page if index % 2 else -page), animate=False, immediate=True)
            # What the window's idle check and the screen's UpdateScroll
            # handler do, so this turn's update lays out the scroll.
            window._check_refresh()
            screen._scroll_required = True
            update = screen._on_timer_update
        else:
            compositor._dirty_regions.add(clip)
            update = screen._compositor_refresh
        written = []
        driver_write = app._driver.write
        app._driver.write = lambda data: (written.append(len(data)), driver_write(data))[1]
        originals = {"partial": Compositor.render_partial_update, "segments": ChopsUpdate.render_segments,
                     "chops": Compositor._render_chops, "layout": Screen._refresh_layout}
        Compositor.render_partial_update = timed_part("partial", originals["partial"])
        ChopsUpdate.render_segments = timed_part("segments", originals["segments"])
        Compositor._render_chops = timed_part("chops", originals["chops"])
        Screen._refresh_layout = timed_part("layout", originals["layout"])
        parts.clear()
        enabled = gc.isenabled()
        gc.disable()
        interval = sys.getswitchinterval()
        profiler = profilers.get(kind)
        if profiled:
            sys.setswitchinterval(1.0)
            profiler.enable()
        begin, cpu = time.perf_counter_ns(), time.thread_time_ns()
        try:
            update()
        finally:
            spent, spent_cpu = time.perf_counter_ns() - begin, time.thread_time_ns() - cpu
            if profiled:
                profiler.disable()
                sys.setswitchinterval(interval)
            if enabled:
                gc.enable()
            Compositor.render_partial_update = originals["partial"]
            ChopsUpdate.render_segments = originals["segments"]
            Compositor._render_chops = originals["chops"]
            Screen._refresh_layout = originals["layout"]
            app._driver.write = driver_write
        if not described:
            # What the viewport is drawn from: each widget's place and the
            # styles its lines are painted with.
            for widget in drawn:
                region, widget_clip = compositor.visible_widgets[widget]
                styles = widget.styles
                described.append({"widget": type(widget).__name__, "region": tuple(region), "clip": tuple(widget_clip),
                                  "padding": tuple(styles.padding), "border": any(edge for edge, _ in styles.border),
                                  "outline": any(edge for edge, _ in styles.outline), "tint": styles.tint.a,
                                  "opacity": widget.opacity, "text_opacity": styles.text_opacity,
                                  "background": str(styles.background), "filters": len(widget.get_line_filters())})
        if not profiled:
            passes.append({"kind": kind, "ms": spent / 1e6, "cpu_ms": spent_cpu / 1e6, "widgets": len(drawn),
                           "rows": clip.height, "columns": clip.width, "bytes": sum(written), **parts})

    schedule = [(kind, False) for kind in ("cold", "warm", "scroll") for _ in range(iterations)]
    schedule += [(kind, True) for kind in ("cold", "scroll") for _ in range(iterations)]

    def step(index: int) -> None:
        if index < len(schedule):
            try:
                paint(*schedule[index], index)
            except Exception:
                import traceback
                with open(output, "w") as file:
                    json.dump({"error": traceback.format_exc()}, file)
                raise
            loop.call_later(0.02, step, index + 1, context=context)
            return
        profilers["cold"].dump_stats(output + ".prof")
        profilers["scroll"].dump_stats(output + ".scroll.prof")

        def summary(kind):
            chosen = [entry for entry in passes if entry["kind"] == kind]
            return {key: round(statistics.median(entry.get(key, 0.0) for entry in chosen), 3)
                    for key in ("ms", "cpu_ms", "layout", "partial", "chops", "segments", "bytes",
                                "widgets", "rows", "columns")}
        partial = output + ".partial"
        with open(partial, "w") as file:
            json.dump({"cold": summary("cold"), "warm": summary("warm"), "scroll": summary("scroll"),
                       "drawn": described, "passes": passes}, file, indent=1)
        os.rename(partial, output)

    loop.call_soon(step, 0, context=context)


def _subject(args) -> str:
    """Which object a traced call was for (its type and id), and who called it."""
    caller, chain = sys._getframe(2), []
    while caller is not None and len(chain) < 8:
        chain.append(f"{caller.f_code.co_qualname}:{caller.f_lineno}")
        caller = caller.f_back
    from textual.geometry import Region, Size

    # Geometry arguments are shown by value: they tell two measurements of
    # the same widget apart. Any other tuple is named by type: printing a
    # large argument costs the traced thread more than the call did.
    def geometry(subject):
        return isinstance(subject, (Size, Region)) or (
            isinstance(subject, tuple) and all(isinstance(item, (int, float)) for item in subject))

    subjects = " ".join(repr(subject) if geometry(subject)
                        else f"{type(subject).__name__}#{getattr(subject, 'id', None) or ''}"
                        for subject in args[:3])
    return f"{subjects} <- {' < '.join(chain)}"


def _result(value) -> str:
    """A short description of what a traced call returned."""
    if value is None or isinstance(value, (bool, int, float)):
        return repr(value)
    if isinstance(value, (list, tuple)):
        return f"{type(value).__name__}[{', '.join(type(item).__name__ for item in value)}]"
    fields = getattr(value, "__dataclass_fields__", None)
    if fields:
        shown = ", ".join(f"{field}={_field(getattr(value, field))}" for field in fields if field != "admissions")
        return f"{type(value).__name__}({shown})"
    return type(value).__name__


def _field(value) -> str:
    """One field of a traced result. A container is counted, not printed:
    printing a large one costs the traced thread more than the call did."""
    if isinstance(value, (dict, list, tuple, set, frozenset)):
        return f"{type(value).__name__}[{len(value)}]"
    return f"{value!r:.40}"


def trace_calls(*, expected_pid, output, targets, seconds=60):
    """Time each call of the named methods ("module:Class.method", sync or async).

    Each record: target, milliseconds, subject and callers, result, start (monotonic ns),
    and the calling thread's CPU milliseconds (below the duration when it waited).
    """
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
        declared = inspect.getattr_static(owner, name)
        original = getattr(owner, name)
        if isinstance(declared, classmethod):
            # Wrap the function itself and redeclare it as a classmethod.
            def timed_class(cls, *args, __original=declared.__func__, __target=target, **kwargs):
                begin, cpu = time.monotonic_ns(), time.thread_time_ns()
                result = __original(cls, *args, **kwargs)
                calls.append((__target, (time.monotonic_ns() - begin) / 1e6, _subject((cls, *args)), _result(result), begin,
                              (time.thread_time_ns() - cpu) / 1e6))
                return result
            setattr(owner, name, classmethod(timed_class))
            restore.append((owner, name, declared))
            continue
        if inspect.iscoroutinefunction(original):
            @functools.wraps(original)
            async def timed(*args, __original=original, __target=target, **kwargs):
                begin, cpu = time.monotonic_ns(), time.thread_time_ns()
                try:
                    return await __original(*args, **kwargs)
                finally:
                    calls.append((__target, (time.monotonic_ns() - begin) / 1e6, _subject(args), None, begin,
                                  (time.thread_time_ns() - cpu) / 1e6))
        else:
            @functools.wraps(original)
            def timed(*args, __original=original, __target=target, **kwargs):
                begin, cpu = time.monotonic_ns(), time.thread_time_ns()
                result = None
                try:
                    result = __original(*args, **kwargs)
                    return result
                finally:
                    calls.append((__target, (time.monotonic_ns() - begin) / 1e6, _subject(args), _result(result), begin,
                                  (time.thread_time_ns() - cpu) / 1e6))
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


def trace_reflows(*, expected_pid, output, seconds=60):
    """Each scoped reflow: duration, roots, widgets placed, shown and hidden."""
    import asyncio
    from textual._compositor import Compositor

    if os.getpid() != expected_pid:
        raise RuntimeError("Unexpected capture process")
    original, records = Compositor.reflow_subtrees, []

    def timed(self, parent, size, roots, **kwargs):
        roots = tuple(roots)
        begin = time.monotonic_ns()
        result = original(self, parent, size, roots, **kwargs)
        records.append(((time.monotonic_ns() - begin) / 1e6,
                        [f"{type(root).__name__}#{root.id or ''}" for root in roots],
                        None if result is None else (len(result.placed), len(result.shown), len(result.hidden)),
                        len(self._visible_map or ())))
        return result

    def full(name):
        method = getattr(Compositor, name)

        def timed_full(self, parent, size, *args, **kwargs):
            # What the screen was asked to lay out when it could not scope it.
            pending = getattr(parent, "_layout_widgets", {})
            requests = sorted(f"{type(widget).__name__}#{widget.id or ''}"
                              + ("" if widget.styles.auto_dimensions else "!")
                              for widget in pending)
            begin = time.monotonic_ns()
            result = method(self, parent, size, *args, **kwargs)
            records.append(((time.monotonic_ns() - begin) / 1e6, [name, *requests], "full",
                            len(self._visible_map or ())))
            return result

        setattr(Compositor, name, timed_full)
        return name, method

    Compositor.reflow_subtrees = timed
    fulls = [full("reflow"), full("reflow_visible")]

    def finish():
        Compositor.reflow_subtrees = original
        for name, method in fulls:
            setattr(Compositor, name, method)
        partial = output + ".partial"
        with open(partial, "w") as file:
            json.dump(records, file)
        os.rename(partial, output)

    asyncio.get_running_loop().call_later(seconds, finish)


def trace_garbage(*, expected_pid, output, seconds=12, min_objects=1000):
    """What each collection that finds at least ``min_objects`` unreachable objects collected.

    For ``seconds`` the collector keeps what it finds (DEBUG_SAVEALL); after
    each collection the found objects are counted by type and released.
    """
    import asyncio
    import collections
    import gc

    if os.getpid() != expected_pid:
        raise RuntimeError("Unexpected capture process")
    records = []
    state = {}

    def collected(phase, info):
        if phase == "start":
            state["begin"] = time.monotonic_ns()
            return
        found = gc.garbage[:]
        gc.garbage.clear()
        if len(found) >= min_objects:
            types = collections.Counter(f"{type(item).__module__}.{type(item).__qualname__}" for item in found)
            # Exceptions and frames held in cycles: which raised, and where.
            types.update(f"raised {type(item).__qualname__}: {str(item)[:60]}"
                         for item in found if isinstance(item, BaseException))
            types.update(f"frame {item.f_code.co_qualname} {item.f_code.co_filename.rsplit('/', 2)[-1]}"
                         for item in found if type(item).__name__ == "frame")
            # The objects nothing else refers to first: what owned the cycle.
            causes = [(name, count) for name, count in types.most_common() if name.startswith(("raised", "frame"))]
            records.append((state["begin"], (time.monotonic_ns() - state["begin"]) / 1e6, info["generation"],
                            len(found), types.most_common(60) + causes[:40]))
        del found

    gc.set_debug(gc.DEBUG_SAVEALL)
    gc.callbacks.append(collected)

    def finish():
        gc.callbacks.remove(collected)
        gc.set_debug(0)
        gc.garbage.clear()
        partial = output + ".partial"
        with open(partial, "w") as file:
            json.dump(records, file)
        os.rename(partial, output)

    asyncio.get_running_loop().call_later(seconds, finish)


def heap_census(*, expected_pid, output, after=10):
    """``after`` seconds from now: the collector's tracked, unfrozen objects counted by type.

    These are what each pass of the cyclic collector scans (frozen objects are not).
    """
    import asyncio
    import collections
    import gc

    if os.getpid() != expected_pid:
        raise RuntimeError("Unexpected capture process")

    def count():
        with measuring_pause():
            objects = gc.get_objects()
            types = collections.Counter(f"{type(item).__module__}.{type(item).__qualname__}" for item in objects)
            # Bound built-ins and weak references: which owners hold them.
            types.update(f"bound {type(item.__self__).__qualname__}.{item.__name__}" for item in objects
                         if type(item).__name__ == "builtin_function_or_method" and item.__self__ is not None)
            types.update(f"weakref to {type(target).__qualname__}" for item in objects
                         if type(item).__name__ == "ReferenceType" and (target := item()) is not None)
            total = len(objects)
            del objects
            # Each ABC's isinstance/issubclass caches (weak references to classes).
            import _abc
            from abc import ABCMeta
            seen, pending, caches = set(), [object], collections.Counter()
            while pending:
                cls = pending.pop()
                for sub in type.__subclasses__(cls) if isinstance(cls, type) else ():
                    if sub not in seen:
                        seen.add(sub)
                        pending.append(sub)
                        if isinstance(sub, ABCMeta):
                            registry, cache, negative, _version = _abc._get_dump(sub)
                            if len(cache) + len(negative) >= 1:
                                caches[f"abc cache {sub.__module__}.{sub.__qualname__}"] = len(cache) + len(negative)
            types.update(caches)
        partial = output + ".partial"
        with open(partial, "w") as file:
            json.dump({"tracked": total, "frozen": gc.get_freeze_count(), "types": types.most_common(3000)}, file)
        os.rename(partial, output)

    asyncio.get_running_loop().call_later(after, count)


def collect_all(*, expected_pid, output, after=70):
    """``after`` seconds from now: one full collection, split into its scan and its frees.

    The first pass keeps what it finds (DEBUG_SAVEALL), so its time is the
    scan of the whole unfrozen heap and the found objects can be counted by
    type; the second pass scans again and frees them. The difference is what
    freeing that garbage costs. Both run inside a measuring pause.
    """
    import asyncio
    import collections
    import gc

    if os.getpid() != expected_pid:
        raise RuntimeError("Unexpected capture process")

    def collect():
        with measuring_pause():
            tracked = len(gc.get_objects())
            gc.set_debug(gc.DEBUG_SAVEALL)
            begin = time.monotonic_ns()
            gc.collect()
            scanned = time.monotonic_ns()
            gc.set_debug(0)
            found = gc.garbage[:]
            gc.garbage.clear()
            types = collections.Counter(f"{type(item).__module__}.{type(item).__qualname__}" for item in found)
            sizes, item = collections.Counter(), None
            for item in found:
                if isinstance(item, (list, tuple, dict, set)):
                    sizes[f"{type(item).__name__} items"] += len(item)
            count = len(found)
            del found, item
            begin_free = time.monotonic_ns()
            gc.collect()
            freed = time.monotonic_ns()
        partial = output + ".partial"
        with open(partial, "w") as file:
            json.dump({"tracked_before": tracked, "found": count, "scan_ms": (scanned - begin) / 1e6,
                       "scan_and_free_ms": (freed - begin_free) / 1e6, "tracked_after": len(gc.get_objects()),
                       "types": types.most_common(60), "container_items": sizes.most_common()}, file)
        os.rename(partial, output)

    asyncio.get_running_loop().call_later(after, collect)


def heap_components(*, expected_pid, output, after=100):
    """``after`` seconds from now: how the unfrozen heap hangs together.

    A collector increment takes an object and everything unfrozen it can
    reach, so its pause is the size of that reachable set, not of the
    increment's budget. This records the largest strongly connected group,
    what it reaches, by type, and how much it would reach if objects of one
    type were not followed (which type ties the set together).
    """
    import asyncio
    import collections
    import gc

    if os.getpid() != expected_pid:
        raise RuntimeError("Unexpected capture process")

    def name(item):
        return f"{type(item).__module__}.{type(item).__qualname__}"

    def measure():
        with measuring_pause():
            objects = gc.get_objects()
            index = {id(item): position for position, item in enumerate(objects)}
            count = len(objects)
            types = [name(item) for item in objects]
            edges = [[index[id(target)] for target in gc.get_referents(item) if id(target) in index]
                     for item in objects]

            def reach(seeds, skip=None):
                seen = bytearray(count)
                pending = list(seeds)
                for seed in pending:
                    seen[seed] = 1
                total = 0
                while pending:
                    node = pending.pop()
                    total += 1
                    if skip is not None and types[node] == skip:
                        continue
                    for target in edges[node]:
                        if not seen[target]:
                            seen[target] = 1
                            pending.append(target)
                return total, seen

            # Strongly connected groups (iterative Tarjan).
            order, low, on_stack, stack, groups = [-1] * count, [0] * count, bytearray(count), [], []
            counter = 0
            for start in range(count):
                if order[start] != -1:
                    continue
                work = [(start, 0)]
                while work:
                    node, edge = work.pop()
                    if edge == 0:
                        order[node] = low[node] = counter
                        counter += 1
                        stack.append(node)
                        on_stack[node] = 1
                    targets = edges[node]
                    descended = False
                    while edge < len(targets):
                        target = targets[edge]
                        edge += 1
                        if order[target] == -1:
                            work.append((node, edge))
                            work.append((target, 0))
                            descended = True
                            break
                        if on_stack[target] and order[target] < low[node]:
                            low[node] = order[target]
                    if descended:
                        continue
                    if low[node] == order[node]:
                        group = []
                        while True:
                            member = stack.pop()
                            on_stack[member] = 0
                            group.append(member)
                            if member == node:
                                break
                        if len(group) > 50:
                            groups.append(group)
                    if work:
                        parent = work[-1][0]
                        if low[node] < low[parent]:
                            low[parent] = low[node]
            groups.sort(key=len, reverse=True)
            report = {"tracked": count, "edges": sum(map(len, edges)), "groups": []}
            for group in groups[:4]:
                total, seen = reach(group[:1])
                reached = collections.Counter(types[node] for node in range(count) if seen[node])
                inside = collections.Counter(types[node] for node in group)
                cuts = sorted(((reach(group[:1], skip=kind)[0], kind) for kind, _ in reached.most_common(40)
                               if types[group[0]] != kind))[:15]
                report["groups"].append({"size": len(group), "types": inside.most_common(25), "reaches": total,
                                         "reached_types": reached.most_common(40), "reaches_without_type": cuts})
            # Objects no unfrozen object refers to: where increments that stay small begin.
            referred = bytearray(count)
            for targets in edges:
                for target in targets:
                    referred[target] = 1
            report["unreferred_types"] = collections.Counter(
                types[node] for node in range(count) if not referred[node]).most_common(25)
            del objects, index, edges
        partial = output + ".partial"
        with open(partial, "w") as file:
            json.dump(report, file)
        os.rename(partial, output)

    asyncio.get_running_loop().call_later(after, measure)


def freeze_heap(*, expected_pid, output):
    """Experiment: freeze the collector's current heap now (what a later freeze policy would do)."""
    import gc

    if os.getpid() != expected_pid:
        raise RuntimeError("Unexpected capture process")
    with measuring_pause():
        before = len(gc.get_objects())
        gc.freeze()
    with open(output, "w") as file:
        json.dump({"frozen_now": before, "frozen_total": gc.get_freeze_count()}, file)


def trace_abc_growth(*, expected_pid, output, seconds=40):
    """Who adds entries to ABC isinstance/issubclass caches (each is two collector-tracked objects)."""
    import _abc
    import asyncio
    import collections
    from abc import ABCMeta

    if os.getpid() != expected_pid:
        raise RuntimeError("Unexpected capture process")
    sources = collections.Counter()
    instancecheck, subclasscheck = ABCMeta.__instancecheck__, ABCMeta.__subclasscheck__

    def size(cls):
        _registry, cache, negative, _version = _abc._get_dump(cls)
        return len(cache) + len(negative)

    def record(cls, checked):
        caller, chain = sys._getframe(2), []
        while caller is not None and len(chain) < 5:
            chain.append(f"{caller.f_code.co_qualname} {caller.f_code.co_filename.rsplit('/', 2)[-1]}")
            caller = caller.f_back
        sources[" < ".join(chain)] += 1

    def counted_instancecheck(cls, instance):
        before = size(cls)
        result = instancecheck(cls, instance)
        if size(cls) > before:
            record(cls, type(instance))
        return result

    def counted_subclasscheck(cls, subclass):
        before = size(cls)
        result = subclasscheck(cls, subclass)
        if size(cls) > before:
            record(cls, subclass)
        return result

    ABCMeta.__instancecheck__, ABCMeta.__subclasscheck__ = counted_instancecheck, counted_subclasscheck

    def finish():
        ABCMeta.__instancecheck__, ABCMeta.__subclasscheck__ = instancecheck, subclasscheck
        partial = output + ".partial"
        with open(partial, "w") as file:
            json.dump(sources.most_common(40), file)
        os.rename(partial, output)

    asyncio.get_running_loop().call_later(seconds, finish)


def trace_posts(*, expected_pid, output, seconds=40):
    """Every message posted to a screen: when, its type and who posted it."""
    import asyncio
    from textual.message_pump import MessagePump
    from textual.screen import Screen

    if os.getpid() != expected_pid:
        raise RuntimeError("Unexpected capture process")
    post, records = MessagePump.post_message, []

    def recorded(self, message):
        if isinstance(self, Screen):
            caller, chain = sys._getframe(1), []
            while caller is not None and len(chain) < 6:
                chain.append(f"{caller.f_code.co_qualname}:{caller.f_lineno}")
                caller = caller.f_back
            sender = getattr(message, "widget", None) or getattr(message, "_sender", None)
            records.append((time.monotonic_ns(), type(message).__qualname__, type(sender).__name__, " < ".join(chain)))
        return post(self, message)

    MessagePump.post_message = recorded

    def finish():
        MessagePump.post_message = post
        partial = output + ".partial"
        with open(partial, "w") as file:
            json.dump(records, file)
        os.rename(partial, output)

    asyncio.get_running_loop().call_later(seconds, finish)


def trace_rules(*, expected_pid, output, seconds=60):
    """Each committed style-rule change: when, on which node, which rules, and whether geometry."""
    import asyncio
    from textual.css.styles import Styles

    if os.getpid() != expected_pid:
        raise RuntimeError("Unexpected capture process")
    original, records = Styles._update_rules, []

    def recorded(self, rules, removals=()):
        rules, removals = tuple(rules), tuple(removals)
        before = dict(self._rules)
        begin = time.monotonic_ns()
        changed = original(self, rules, removals)
        if changed and (node := self.node) is not None:
            keys = sorted({key for key, value in rules if before.get(key) != value}
                          | {key for key in removals if key in before})
            records.append((begin, (time.monotonic_ns() - begin) / 1e6,
                            f"{type(node).__name__}#{getattr(node, 'id', None) or ''}", keys))
        return changed

    Styles._update_rules = recorded

    def finish():
        Styles._update_rules = original
        partial = output + ".partial"
        with open(partial, "w") as file:
            json.dump(records, file)
        os.rename(partial, output)

    asyncio.get_running_loop().call_later(seconds, finish)


def trace_exit(*, expected_pid, output):
    """Write who asks the app to exit, and when the process ends, as it happens."""
    import atexit
    import traceback
    from textual.app import App

    if os.getpid() != expected_pid:
        raise RuntimeError("Unexpected capture process")
    original = App.exit

    def note(text):
        with open(output, "a") as file:
            file.write(f"{time.time():.3f} {text}\n")

    def exit(self, *args, **kwargs):
        note("App.exit " + repr((args, kwargs)) + "\n" + "".join(traceback.format_stack(limit=25)))
        return original(self, *args, **kwargs)

    App.exit = exit
    atexit.register(note, "process exit")
    note("installed")


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
        # Tab switches' loop turns over 20 us: how many and the longest.
        "switch_turns": [len(data.get("switch_steps", [])),
                         round(max((spent for _begin, spent in data.get("switch_steps", [])), default=0), 2)],
        # Per layout run in steps (or with a step over 4 ms): steps and the longest step.
        "stepped_layouts": [[len(steps), round(max(steps), 2)]
                            for _begin, _step_ns, steps in data.get("stepped_layouts", []) if steps],
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
