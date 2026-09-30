"""Projected history shares bounded paging and can revisit every selected record."""

from toad.widgets.message_filter import ThinkingCategory

import asyncio
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from agent_comms.transcripts import TranscriptCursor, TranscriptPage
from agent_comms.transcript_events import AssistantTranscript, ThinkingTranscript
from textual.selection import SELECT_ALL
from textual.widgets._markdown import MarkdownParagraph

from runtime_fixture import ToadApp
from toad.widgets.message_filter import all_categories, MessageCategory
from toad.widgets.presentation_window import PresentationBudget
from toad.widgets.transcript_history import TranscriptHistory



async def exercise(app, pilot, count, *, matches=True):
    view = app.selected_session.conversation
    view.visible_categories = all_categories()
    events = tuple(
        (ThinkingTranscript if matches and index % 31 == 0 else AssistantTranscript)( f"record-{index}")
        for index in range(count)
    )
    identity = f"projection-{count}-{matches}"

    async def load(*, before=None, after=None, through=None):
        limit = through.offset if through is not None else count
        if after is not None:
            start, stop = after.offset, min(limit, after.offset + 32)
        else:
            stop = min(limit, before.offset if before is not None else limit)
            start = max(0, stop - 32)
        return TranscriptPage(events[start:stop], TranscriptCursor(identity, start),
                              TranscriptCursor(identity, stop), start > 0, stop < limit)

    budget = PresentationBudget(max_items=6, admission_items=2, reserve_batches=0)
    canonical = await load()
    history = TranscriptHistory(canonical, load, budget=budget)
    seen, returned = set(), set()
    peak_fragments = peak_pages = peak_widgets = 0
    with (patch.object(TranscriptHistory, "_check_edges"),
          patch.object(TranscriptHistory, "_warm_pages")):
        await view.contents.mount(history)
        await pilot.pause()
        start = history.pages[0].start
        boundary = canonical.before.offset + start
        expected = {event.text for event in events[:boundary] if event.declared_name == "thinking"}
        view.visible_categories = frozenset({ThinkingCategory})
        view.window.release_anchor()
        while history.filter.has_older:
            view.window.scroll_to(y=0, animate=False, immediate=True)
            await pilot.pause(0)
            await history.filter.scan_older()
            overlay = history.filter.overlay
            assert overlay is not None
            seen.update(child.fragment.events[0].text for child in overlay.fragment_views)
            peak_fragments = max(peak_fragments, overlay.fragment_count)
            peak_pages = max(peak_pages, len(overlay.pages))
            peak_widgets = max(peak_widgets, overlay.widget_count)
            # Each fixture row occupies at least one line. The viewport can
            # protect its rows plus partially clipped ends and one new batch.
            bound = budget.item_limit(view.window.size.height + 2 + budget.admission_items)
            assert overlay.fragment_count <= bound, (count, overlay.fragment_count, bound)
            assert len(overlay.pages) <= bound, (count, len(overlay.pages), bound)
            assert history.pages[0].page is canonical
        assert seen == expected, (count, expected - seen, seen - expected)
        overlay = history.filter.overlay
        assert overlay is not None
        source = overlay._reader()
        returned.update(child.fragment.events[0].text for child in overlay.fragment_views)
        while overlay.has_newer:
            view.window.scroll_to(y=view.window.max_scroll_y, animate=False, immediate=True)
            await pilot.pause(0)
            await overlay.reserve_source_work().execute(overlay, lambda: overlay._load_page(False))
            names = [child.fragment.events[0].text for child in overlay.fragment_views]
            assert len(names) == len(set(names)), "Revisiting duplicated projected records"
            returned.update(names)
        assert returned == expected, (count, expected - returned, returned - expected)

        if matches and count == 800:
            await pilot.pause()
            selected = overlay.fragment_views[-1].query_one(MarkdownParagraph)
            selected_text = selected.render().plain
            app.screen.selections = {selected: SELECT_ALL}
            for _ in range(4):
                view.window.scroll_to(y=0, animate=False, immediate=True)
                await pilot.pause(0)
                await overlay.reserve_source_work().execute(overlay, lambda: overlay._load_page(True))
            assert selected.is_attached and selected_text in app.screen.get_selected_text()
            app.screen.clear_selection()

        if not matches:
            assert overlay.fragment_count == 0
            assert len(overlay.pages) <= 2, "Unmatched pages accumulated empty widget shells"
        view.visible_categories = all_categories()
        await pilot.pause()
        assert history.filter.overlay is None and source.closed
        assert history.pages[0].page is canonical
        await history.remove()
        await pilot.pause()
    print(json.dumps({"source_records": count, "matching": len(expected),
                      "peak_fragments": peak_fragments, "peak_pages": peak_pages,
                      "peak_widgets": peak_widgets}), flush=True)


async def main():
    for field, value in (("max_items", 0), ("admission_items", -1),
                         ("reserve_batches", True), ("widgets_per_row", -1)):
        try:
            PresentationBudget(**{field: value})
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid presentation budget accepted")
    with TemporaryDirectory(prefix="toad-projected-budget-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(100, 26)) as pilot:
            await pilot.pause()
            for count in (80, 800, 8000):
                await exercise(app, pilot, count)
            await exercise(app, pilot, 8000, matches=False)
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("projected history: 100x source growth, bounded rows, bidirectional coverage and selection preserved")


if __name__ == "__main__":
    asyncio.run(main())
