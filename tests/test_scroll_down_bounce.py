"""Downward wheel travel must not publish a backwards reader after page eviction."""

from functools import partial
from inspect import getfile
from pathlib import Path

from textual import events

from agent_comms.session_file import RegistrySessionLocation
from agent_comms.threads import Thread
from support import journals
from toad.app import ToadApp
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

    def _on_frame_published(self):
        super()._on_frame_published()
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
        reader = (fragment.arrival_position, fragment.part_position.index, span.index,
                  (y - first - span.first) / span.height)
        self.frames.append((y, reader, page.prepared.start, page.prepared.stop))


def recorded_app(**kwargs):
    app = ToadApp(**kwargs)
    app.remove_mode("workspace")
    app.add_mode("workspace", partial(RecordedHistoryScreen, id="workspace"))
    return app


async def wheel(ui, window, event_type):
    """Send a real wheel event through the screen's normal mouse route."""
    _app, pilot = ui.textual
    await pilot._post_mouse_events([event_type], window, offset=(3, 3))


async def test_scroll_down_through_evicted_pages_never_moves_up(workspace):
    journal = journals.write_journal(workspace.project / "long-history.jsonl", *(
        journals.assistant_entry(
            f"Message {index:04d}: retained Markdown rows.",
            id=f"a{index}", parent=f"a{index - 1}" if index else None)
        for index in range(600)))
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
        # Walk backwards through the real lazy pager before measuring downward travel.
        print("P758 initial:", window.scroll_y, window.max_scroll_y,
              [(page.prepared.start, page.prepared.stop) for page in history.pages], flush=True)
        for _ in range(2048):
            await wheel(ui, window, events.MouseScrollUp)
            if history.has_more(NEWER_END):
                break
        await ui.step()
        print("P758 after upward setup:", window.scroll_y, window.max_scroll_y,
              [(page.prepared.start, page.prepared.stop) for page in history.pages], flush=True)
        assert not window.follows_tail
        assert history.has_more(NEWER_END)
        oldest = history.pages[0].prepared.fragments_in_range[0].arrival_position
        screen = ui.app.screen
        screen.recording = True
        for _ in range(2048):
            await wheel(ui, window, events.MouseScrollDown)
            if window.follows_tail:
                break
        await ui.step()
        screen.recording = False
        frames = screen.frames
        print("P758 per-published-frame (scroll_y, reader, range_start, range_stop):", flush=True)
        for frame in frames:
            print(frame, flush=True)
        assert len(frames) > 10, frames
        assert history.pages[0].prepared.fragments_in_range[0].arrival_position > oldest, (
            "No older fragments were evicted during downward travel")
        backwards = [(before, after) for before, after in zip(frames, frames[1:])
                     if after[1] < before[1]]
        assert not backwards, f"Downward inputs published backwards reader movement: {backwards}"
