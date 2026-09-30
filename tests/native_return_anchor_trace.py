"""Diagnose the installed saved-reader journey without replacing its effects."""
import asyncio
import functools
import json
import os
from pathlib import Path
from time import monotonic
import traceback

from toad.widgets.history_anchor import HistoryWindow
from native_loaded_return_cache_pilot import PaintedReturnApp, acceptance
from l0a_native_installed_pilot import main


def reader_state(window):
    from toad.screens.session_view import SessionView

    return dict(window=id(window), source=window.app.selected_mode,
                owning_source=window.query_ancestor(SessionView).id,
                scroll_y=window.scroll_y, maximum_y=window.max_scroll_y,
                revision=window.scroll_revision, follows_tail=window.follows_tail,
                anchored=window.is_anchored, anchor_released=window._anchor_released,
                layout_anchor=(type(window.history_anchor).__name__
                               if window.history_anchor is not None else None),
                lock_held=window.history_lock.locked())


def trace_anchor(method, records, *, transitions_only=False):
    @functools.wraps(method)
    def traced(window, *args, **kwargs):
        before = reader_state(window)
        started = monotonic()
        result = method(window, *args, **kwargs)
        after = reader_state(window)
        if not transitions_only or before != after:
            records.append(dict(operation=method.__name__, clock=started,
                                completed=monotonic(), before=before, after=after,
                                histories=[dict(identity=id(history), through=repr(history.through))
                                           for history in window.histories],
                                stack=traceback.format_stack(limit=14)))
        return result
    return traced


if __name__ == '__main__':
    methods = ('anchor', 'release_anchor', '_check_anchor', 'check_follow',
               'restore_history_layout')
    originals = {name: getattr(HistoryWindow, name) for name in methods}
    records = []
    try:
        for name, method in originals.items():
            setattr(HistoryWindow, name, trace_anchor(
                method, records, transitions_only=name not in {'anchor', 'release_anchor'}))
        asyncio.run(main(app_type=PaintedReturnApp, acceptance=acceptance,
                         provider_request_budget=2 * int(os.environ.get('NATIVE_RETURN_PROMPTS', '2')) + 2))
    finally:
        for name, method in originals.items():
            setattr(HistoryWindow, name, method)
        # Flush once after ordinary teardown; synchronous disk writes on every
        # anchor call can alter precisely the asynchronous ordering under study.
        path = Path(os.environ['L0A_EVIDENCE']) / 'reader-trace.jsonl'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(''.join(json.dumps(record) + '\n' for record in records))
