"""Textual-facing: a filtered projection of a long history pages through the window with bounded admission and can revisit every selected record.

Not carried over from the old script: the selected paragraph widget surviving four more admissions and the
materialized widget peak (history is line-drawn; selection and widget trees are not part of the page).
"""

from unittest.mock import patch

import pytest

from agent_comms.transcript_events import AssistantTranscript, ThinkingTranscript
from agent_comms.transcripts import NativeTranscriptCursor, TranscriptPage
from support.roots import FIXTURE_SNAPSHOT

from toad.widgets.message_filter import ThinkingCategory, all_categories
from toad.widgets.presentation_window import PresentationBudget
from toad.widgets.transcript_history import TranscriptHistory


def test_an_invalid_presentation_budget_is_refused():
    for field, value in (("max_items", 0), ("batch_items", -1), ("reserve_batches", True), ("widgets_per_row", -1)):
        with pytest.raises(ValueError):
            PresentationBudget(**{field: value})


def shown_texts(projection):
    return [fragment.events[0].text for fragment in projection.fragments_in_range]


@pytest.mark.parametrize("count,matches", [(80, True), (800, True), (8000, True), (8000, False)])
async def test_projection_scans_older_history_within_bounds_and_revisits_every_match(workspace, count, matches):
    events = tuple((ThinkingTranscript if matches and index % 31 == 0 else AssistantTranscript)(f"record-{index}")
                   for index in range(count))
    identity = f"projection-{count}-{matches}"

    async def load(*, before=None, after=None, through=None):
        limit = through.offset if through is not None else count
        if after is not None:
            start, stop = after.offset, min(limit, after.offset + 32)
        else:
            stop = min(limit, before.offset if before is not None else limit)
            start = max(0, stop - 32)
        return TranscriptPage(events[start:stop], NativeTranscriptCursor(identity, start),
                              NativeTranscriptCursor(identity, stop), start > 0, stop < limit, FIXTURE_SNAPSHOT)

    async with workspace.app(size=(100, 26)) as ui:
        view = ui.conversation
        view.visible_categories = all_categories()
        budget = PresentationBudget(max_items=6, batch_items=2, reserve_batches=0)
        canonical = await load()
        history = TranscriptHistory(canonical, load, budget=budget)
        seen, returned = set(), set()
        with patch.object(TranscriptHistory, "_check_edges"):
            await view.contents.mount(history)
            await ui.until(lambda: history.is_mounted, why="the history mounted")
            start = history.pages[0].start
            boundary = canonical.before.offset + start
            expected = {event.text for event in events[:boundary] if event.declared_name == "thinking"}
            view.visible_categories = frozenset({ThinkingCategory})
            view.window.release_anchor()
            while history.filter.has_older:
                view.window.scroll_to(y=0, animate=False, immediate=True)
                await ui.step(0)
                await history.filter.scan_older()
                overlay = history.filter.overlay
                assert overlay is not None
                seen.update(shown_texts(overlay))
                # Each fixture row occupies at least one line. The viewport can protect its rows,
                # partially clipped ends and one new batch.
                bound = budget.item_limit(view.window.size.height + 2 + budget.batch_items)
                assert overlay.fragment_count <= bound, (count, overlay.fragment_count, bound)
                assert len(overlay.pages) <= bound, (count, len(overlay.pages), bound)
                assert history.pages[0].page is canonical
            assert seen == expected, (count, expected - seen, seen - expected)
            overlay = history.filter.overlay
            assert overlay is not None
            source = overlay._reader()
            returned.update(shown_texts(overlay))
            while overlay.has_newer:
                view.window.scroll_to(y=view.window.max_scroll_y, animate=False, immediate=True)
                await ui.step(0)
                await overlay.reserve_source_work().execute(overlay, lambda: overlay._load_page(False))
                names = shown_texts(overlay)
                assert len(names) == len(set(names)), "Revisiting duplicated projected records"
                returned.update(names)
            assert returned == expected, (count, expected - returned, returned - expected)
            if not matches:
                assert overlay.fragment_count == 0
                assert len(overlay.pages) <= 2, "Unmatched pages accumulated empty page shells"
            view.visible_categories = all_categories()
            await ui.until(lambda: history.filter.overlay is None and source.closed, why="the projection retired")
            assert history.pages[0].page is canonical
