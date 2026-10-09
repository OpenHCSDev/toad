"""Total UI-thread work per frame and input-to-paint latency in a live Textual app.

``install`` runs inside the application (through ``capture_live.py --frame-meter``).
Every event-loop callback is timed; a frame is the UI-thread work done since the
previous frame was handed to the driver. An input event is timed from the moment
the driver posts it to the App until the first frame handed over after its last
handler returns. ``python frame_meter.py RESULT.json`` prints the series-table numbers.
"""

import json
import os
import statistics
import sys
import time


def install(*, expected_pid, seconds, output):
    import asyncio
    from asyncio import events as loop_events
    from textual import events
    from textual._context import active_app
    from textual.message_pump import MessagePump

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
    state = {"busy": 0, "current": None}
    frames, inputs, slow = [], {}, []
    run, post, dispatch = loop_events.Handle._run, MessagePump.post_message, MessagePump._dispatch_message
    app_type = type(app)
    display = app_type._display

    def timed_run(handle):
        state["current"] = begin = clock()
        try:
            return run(handle)
        finally:
            state["busy"] += clock() - begin
            state["current"] = None

    def timed_display(self, screen, renderable):
        result = display(self, screen, renderable)
        if renderable is not None and self is app:
            now = clock()
            running = 0 if state["current"] is None else now - state["current"]
            frames.append((now, (state["busy"] + running) / 1e6))
            # The running callback adds its full duration when it returns;
            # the part already counted in this frame is subtracted here.
            state["busy"] = -running
        return result

    def timed_post(self, message):
        if self is app and isinstance(message, inputs_types) and id(message) not in inputs:
            inputs[id(message)] = [clock(), None, type(message).__name__, []]
        return post(self, message)

    async def timed_dispatch(self, message):
        begin = clock()
        try:
            return await dispatch(self, message)
        finally:
            end = clock()
            if (entry := inputs.get(id(message))) is not None:
                entry[1] = end
                entry[3].append((type(self).__name__, begin, end))
            if end - begin > 50_000_000:
                slow.append((begin, (end - begin) / 1e6, type(self).__name__, type(message).__qualname__))

    def finish():
        loop_events.Handle._run = run
        MessagePump.post_message = post
        MessagePump._dispatch_message = dispatch
        app_type._display = display
        fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as file:
            json.dump({"pid": expected_pid, "seconds": seconds,
                       "frames": frames, "inputs": list(inputs.values()),
                       "slow_handlers": slow}, file)

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
    screen = app.screen
    rows = {row.target_name: tuple(row.region) for row in screen.query("ThreadRow") if row.region}
    tabs = [tuple(tab.region) for tab in screen.query("SessionLabel") if tab.region]
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as file:
        json.dump({"threads": rows, "tabs": tabs}, file)


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))] if ordered else float("nan")


def summarize(path):
    data = json.load(open(path))
    frames = data["frames"]
    work = [busy for _end, busy in frames]
    ends = [end for end, _busy in frames]
    latencies = []
    position = 0
    for arrived, handled, *_ in sorted((i for i in data["inputs"] if i[1] is not None), key=lambda i: i[0]):
        while position < len(ends) and ends[position] < handled:
            position += 1
        if position < len(ends):
            latencies.append((ends[position] - arrived) / 1e6)
    return {
        "frames": len(work), "inputs": len(data["inputs"]), "painted_inputs": len(latencies),
        "frame_median_ms": round(statistics.median(work), 1) if work else None,
        "frame_p95_ms": round(percentile(work, .95), 1),
        "input_to_paint_median_ms": round(statistics.median(latencies), 1) if latencies else None,
        "input_to_paint_p95_ms": round(percentile(latencies, .95), 1),
    }


if __name__ == "__main__":
    print(json.dumps(summarize(sys.argv[1]), indent=2))
