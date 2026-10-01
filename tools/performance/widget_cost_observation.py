"""Exact subtree-walk invocation counts on the recorder's original UI process."""

import json
import os
from pathlib import Path
import sys
from time import monotonic_ns


def install(*, expected_pid, output):
    from textual.widget import Widget
    from toad.widgets.viewport_body import MeasuredViewportBody

    if os.getpid() != expected_pid:
        raise RuntimeError("Widget cost observation process identity changed")
    path = Path(output).resolve()
    if not path.is_relative_to((Path.home() / '.cache/agent-scratch').resolve()):
        raise ValueError("Widget cost trace requires recorder-owned persistent scratch")
    tool = sys.monitoring.PROFILER_ID
    if sys.monitoring.get_tool(tool) is not None:
        raise RuntimeError("Monitoring slot already owned; preserve its observer")
    stream = path.open('x', buffering=1)
    walk = Widget.walk_children.__code__
    cost = MeasuredViewportBody.retained_widget_count.fget.__code__
    started_ns = monotonic_ns()
    totals = dict(all_walks=0, retained_cost_walks=0, height_cost_walks=0, diagnostic_walks=0)
    observed_ns = 0
    last_ns = started_ns

    def emit(kind, **facts):
        stream.write(json.dumps(dict(event=kind, monotonic_ns=monotonic_ns(),
            started_ns=started_ns, observer_ns=observed_ns, **totals, **facts))+'\n')

    def entered(code, offset):
        nonlocal observed_ns, last_ns
        began = monotonic_ns()
        totals['all_walks'] += 1
        frame = sys._getframe(1).f_back
        in_cost = height = diagnostic = False
        while frame is not None:
            in_cost |= frame.f_code is cost
            height |= frame.f_code.co_name == 'get_content_height'
            diagnostic |= frame.f_code.co_filename.endswith((
                '/tools/performance/capture_state.py', '/tools/performance/capture_screen.py'))
            frame = frame.f_back
        if diagnostic:
            totals['diagnostic_walks'] += 1
        elif in_cost:
            totals['retained_cost_walks'] += 1
            totals['height_cost_walks'] += int(height)
        if began-last_ns >= 1_000_000_000:
            emit('counts')
            last_ns = began
        observed_ns += monotonic_ns()-began

    sys.monitoring.use_tool_id(tool, 'toad-recorder-widget-cost')
    sys.monitoring.register_callback(tool, sys.monitoring.events.PY_START, entered)
    sys.monitoring.set_local_events(tool, walk, sys.monitoring.events.PY_START)
    emit('installed', walk_source=walk.co_filename, cost_source=cost.co_filename)

    def checkpoint(label):
        emit('checkpoint', label=label)

    return checkpoint
