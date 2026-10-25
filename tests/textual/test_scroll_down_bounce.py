"""Textual-facing: downward wheel travel never publishes a backwards reader after page eviction."""

import asyncio
from functools import partial
import gzip
from inspect import getfile
from pathlib import Path

from textual import events
from textual.pilot import _get_mouse_message_arguments

from agent_comms.session_file import RegistrySessionLocation
from agent_comms.threads import Thread
from toad.app import ToadApp
from toad.line_blocks import ToggleDetails
from toad.preferences import SETTINGS
from toad.screens.main import MainScreen
from toad.screens.workspace import WorkspaceScreen
from toad.tab_identity.kinds import MailboxTab
from toad.widgets.conversation import Conversation
from toad.widgets.presentation_window import NEWER_END
from toad.widgets.transcript_history import TranscriptHistory


class RecordedHistoryScreen(WorkspaceScreen):
    """Observe the native publication hook without replacing application methods."""

    CSS_PATH = [Path(getfile(WorkspaceScreen)).parent / path for path in WorkspaceScreen.CSS_PATH]
    recording = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.frames = []
        self.next_frame = asyncio.Event()

    def _on_frame_published(self):
        super()._on_frame_published()
        self.next_frame.set()
        if not self.recording:
            return
        window = self.query_one(Conversation).window
        y = window.scroll_y
        placed = sorted(((first, page) for page, first in window.placements(window.drawn_pages())
                         if first + page.line_count > y), key=lambda item: item[0])
        if not placed:
            return
        first, page = placed[0]
        span = page.fragment_at(max(0, int(y - first)))
        if span is None:
            return
        fragment = span.fragment
        # Distinct fragments may share source position and part. Observe their
        # source-page order too: moving to the next occurrence resets its block.
        reader = (fragment.arrival_position, fragment.part_position.index,
                  page.prepared.fragments.index(fragment), span.index,
                  (y - first - span.first) / span.height)
        self.frames.append((y, reader, page.prepared.start, page.prepared.stop))


def recorded_app(**kwargs):
    app = ToadApp(**kwargs)
    app.remove_mode("workspace")
    app.add_mode("workspace", partial(RecordedHistoryScreen, id="workspace"))
    return app


async def wheel(ui, window, event_type):
    """Feed Pilot's native mouse route without draining page preparation.

    Pilot._post_mouse_events waits for an idle screen before and after every
    event. A real wheel does not wait for the next page to finish preparing.
    Publications pace input while that preparation remains free to overlap it.
    """
    arguments = _get_mouse_message_arguments(window, (3, 3), button=0,
                                             shift=False, meta=False, control=False)
    ui.app.screen.next_frame.clear()
    await ui.app._post_message_and_wait(event_type(**arguments))
    async with asyncio.timeout(10):
        await ui.app.screen.next_frame.wait()


async def test_scroll_down_through_evicted_pages_never_moves_up(workspace):
    # Derived from the laptop's saved mfd conversation, not invented heights.
    # Native entry kinds, text whitespace/punctuation/cell widths and identities
    # are retained; letters/digits are masked and image pixels are blanked.
    fixture = Path(__file__).parents[1] / "fixtures" / "laptop_scroll_shape.jsonl.gz"
    journal = workspace.project / "laptop-history.jsonl"
    journal.write_bytes(gzip.decompress(fixture.read_bytes()))
    owner = workspace.comms.registry.declare(Thread(
        "scroll-reader", frozenset(), str(workspace.project),
        session_file=RegistrySessionLocation.from_path(journal, workspace.comms.root)))
    root = str(workspace.comms.root)
    async with workspace.app(size=(100, 32), session=False, application=recorded_app) as ui:
        ui.app.saved_settings.set(SETTINGS.ui.history_buffer_viewports, 1)
        await ui.app.session_navigation.new(
            MailboxTab(owner.incarnation, root),
            partial(MainScreen.from_thread, workspace.project, root, owner.incarnation),
            original=(root, owner.incarnation))
        await ui.until(lambda: ui.conversation.transcript.reports_coverage,
                       why="the retained transcript to load")
        window = ui.conversation.window
        history = ui.conversation.contents.query_one(TranscriptHistory)
        await ui.until(lambda: history.pages and all(page.rows_measured for page in history.pages),
                       why="the initial retained page to be measured")
        # Walk backwards through the real lazy pager before measuring downward travel.
        for _ in range(4096):
            await wheel(ui, window, events.MouseScrollUp)
            if history.has_more(NEWER_END):
                break
        await ui.step()
        assert not window.follows_tail
        assert history.has_more(NEWER_END)
        oldest = history.pages[0].prepared.fragments_in_range[0].arrival_position
        screen = ui.app.screen
        screen.recording = True
        for _ in range(8192):
            await wheel(ui, window, events.MouseScrollDown)
            if len(screen.frames) > 1 and screen.frames[-1][1] < screen.frames[-2][1]:
                break
            if window.follows_tail:
                break
        await ui.step()
        screen.recording = False
        frames = screen.frames
        assert len(frames) > 1, frames
        backwards = [(before, after) for before, after in zip(frames, frames[1:])
                     if after[1] < before[1]]
        assert not backwards, f"Downward inputs published backwards reader movement: {backwards}"
        assert history.pages[0].prepared.fragments_in_range[0].arrival_position > oldest, (
            "No older fragments were evicted during downward travel")

        # Activate an actual disclosure link on a second occurrence, not a
        # reconstructed source identity. The first occurrence must not steal it.
        candidates = []
        for _ in range(8192):
            await wheel(ui, window, events.MouseScrollUp)
            for page in history.pages:
                for fragment in page.prepared.fragments_in_range:
                    occurrence = page.occurrence_of(fragment)
                    if occurrence > 0 and fragment.has_details:
                        for span in page.fragment_row(fragment.arrival_position,
                                fragment.part_position.index, 0, occurrence).locations():
                            if span.drawn:
                                candidates.append((page, fragment, span, occurrence))
            if candidates:
                break
        assert candidates, "No second occurrence with a disclosure link was loaded"
        page, fragment, span, occurrence = candidates[0]
        destination = window.row_of(page) + span.first
        window.scroll_to(y=destination, animate=False, immediate=True)
        await ui.step()
        links = []
        for row in page.fragment_rows(fragment):
            x = 0
            for segment in page.render_line(row):
                if segment.style is not None and segment.style.meta.get("@click") == ToggleDetails().click:
                    links.append((x, row))
                x += segment.cell_length
        assert links, "The second occurrence has no rendered disclosure link"
        before = fragment.shown.details_open
        _app, pilot = ui.textual
        await pilot.click(page, offset=links[0])
        await ui.until(lambda: fragment.shown.details_open != before,
                       why="the clicked second occurrence's disclosure to toggle")
        await ui.step()
        assert window.scroll_y == destination, (destination, window.scroll_y)
        assert page.occurrence_of(fragment) == occurrence
        print(f"second-occurrence click lands on {window.scroll_y}; occurrence={occurrence}")
