"""Textual-facing: the session details panel shows saved-history availability independently of the bus-input verification status.

The old script replayed a captured ACP log given on its command line; this builds the saved page from events instead.
Not carried over: the readiness of per-message response widgets and the paint of a page's responses by widget
region (history is line-drawn; the words are asked of the screen).
"""

import re

from agent_comms.transcript_events import AssistantTranscript
from agent_comms.transcripts import TranscriptCursor, TranscriptPage

from toad.widgets.session_details import SessionDetails
from toad.widgets.transcript_history import TranscriptHistory


def saved_page():
    cursor = TranscriptCursor("saved-page-proof", 1)
    events = tuple(AssistantTranscript(
        f"Response number {number} describes interesting particular observations about segmentation.\n\n"
        "Another paragraph with considerable additional vocabulary appears afterwards.") for number in range(6))
    return TranscriptPage(events, cursor, cursor, False, False)


async def test_saved_history_is_available_for_every_native_status_and_the_page_is_shown_once(workspace):
    page = saved_page()
    async with workspace.app(size=(140, 42)) as ui:
        view = ui.conversation
        agent = ui.detached_agent()
        ui.attach_agent(agent)
        details = view.query_one(SessionDetails)
        view.native_history_status = "unavailable"
        await ui.until(lambda: "Bus input verification unavailable" in details.title, why="the bus-input warning")
        assert "Saved history not loaded" in details.title

        await view.transcript.snapshot(page)
        await ui.until(lambda: view.query(TranscriptHistory), why="the saved history mounted")
        source = view.query_one(TranscriptHistory)
        await ui.until(lambda: "Saved history available" in details.title, why="saved history reported available")
        assert source.state.reports_coverage
        assert "Bus input verification unavailable" in details.title
        assert "History unavailable" not in details.title

        # The same page again, after the displayed cursor is forgotten, adds nothing.
        before = tuple(view.contents.children)
        view.transcript.displayed_cursor = None
        await view.transcript.snapshot(page)
        await ui.step(0.3)
        assert tuple(view.contents.children) == before
        assert len(view.window.histories) == 1

        words = {word.lower() for event in page.events for word in re.findall(r"[A-Za-z]{8,}", event.text)}
        painted = set(re.findall(r"[a-z]{8,}", ui.visible_text().lower()))
        assert len(words & painted) >= 3, "Words of the saved responses must be painted in the window"

        for status in ("none", "coverage_only", "proven", "unavailable"):
            view.native_history_status = status
            await ui.until(lambda: ("Bus input verification unavailable" in details.title) == (status == "unavailable"),
                           why=f"the bus-input warning for status {status}")
            assert "Saved history available" in details.title
        details.collapsed = False
        await ui.until(lambda: "check the ACP log" in str(details.history.render()), why="the ACP log hint")
        assert "Saved history available" in details.overview_text
        assert not agent.permissions.pending
