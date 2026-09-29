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


def trace_anchor(method):
    @functools.wraps(method)
    def traced(window, *args, **kwargs):
        record = dict(operation=method.__name__, clock=monotonic(),
                      window=id(window), source=window.app.selected_mode,
                      scroll_y=window.scroll_y, revision=window.scroll_revision,
                      follows_tail=window.follows_tail,
                      histories=[dict(identity=id(history), through=repr(history.through))
                                 for history in window.histories],
                      stack=traceback.format_stack(limit=14))
        with (Path(os.environ['L0A_EVIDENCE']) / 'reader-trace.jsonl').open('a') as stream:
            stream.write(json.dumps(record) + '\n')
        return method(window, *args, **kwargs)
    return traced


if __name__ == '__main__':
    original_anchor, original_release = HistoryWindow.anchor, HistoryWindow.release_anchor
    try:
        HistoryWindow.anchor = trace_anchor(original_anchor)
        HistoryWindow.release_anchor = trace_anchor(original_release)
        asyncio.run(main(app_type=PaintedReturnApp, acceptance=acceptance,
                         provider_request_budget=2 * int(os.environ.get('NATIVE_RETURN_PROMPTS', '2')) + 2))
    finally:
        HistoryWindow.anchor, HistoryWindow.release_anchor = original_anchor, original_release
