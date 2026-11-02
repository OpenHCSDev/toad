"""Textual-facing: the window's top edge. Upward wheel travel never moves the reader forward, past live thoughts or through saved history; a wrapped message header pins the moment its first row leaves, drawn exactly as the flow draws it."""


from functools import partial

import pytest
from textual import events

from toad.widgets.agent_response import AgentResponse
from toad.widgets.agent_thought import AgentThought

from test_scroll_down_bounce import RecordedHistoryScreen, recorded_app, wheel
from toad.widgets.conversation import Conversation
from toad.widgets.presentation_window import OLDER_END


THOUGHTS = ("Preparing branch notice tests", "Parametrizing rename routing tests",
            "Checking ThreadIncarnation lookup", "Checking self-delivery behavior",
            "Testing concurrency lock plumbing", "Preparing lifecycle test fixture")


@pytest.mark.parametrize("before", ["response", "thoughts-first"])
async def test_wheel_up_passes_live_thoughts(workspace, before):
    async with workspace.app(size=(100, 32), application=recorded_app) as ui:
        view = ui.conversation
        if before == "response":
            await view.post(AgentResponse("\n\n".join(f"Earlier paragraph {i}" for i in range(40))))
        for thought in THOUGHTS:
            await view.post(AgentThought(f"**{thought}**\n\n"))
        await view.post(AgentResponse("\n\n".join(f"Later paragraph {i}" for i in range(40))))
        window = view.window
        window.anchor()
        await ui.until(lambda: window.max_scroll_y > 0 and window.follows_tail, why="a scrollable tail")
        travel = [window.scroll_y]
        for _ in range(400):
            await wheel(ui, window, events.MouseScrollUp)
            travel.append(window.scroll_y)
            if window.scroll_y == 0:
                break
        backwards = [(index, before, after) for index, (before, after)
                     in enumerate(zip(travel, travel[1:])) if after > before]
        assert not backwards, f"Upward wheel moved the reader down: {backwards} in {travel}"
        assert travel[-1] == 0, f"Upward wheel never reached the top: {travel[-12:]}"


@pytest.mark.parametrize("size", [(100, 32), (50, 44)])
async def test_wheel_up_through_saved_history_never_moves_forward(workspace, size):
    """The laptop's saved conversation shape: thoughts after channel messages, agent replies and tools."""
    import gzip
    from functools import partial
    from pathlib import Path

    from agent_comms.repo import Checkout
    from agent_comms.session_file import RegistrySessionLocation
    from agent_comms.threads import Thread
    from toad.screens.main import MainScreen
    from toad.tab_identity.kinds import MailboxTab
    from toad.widgets.transcript_history import TranscriptHistory

    fixture = Path(__file__).parents[1] / "fixtures" / "laptop_scroll_shape.jsonl.gz"
    journal = workspace.project / "laptop-history.jsonl"
    journal.write_bytes(gzip.decompress(fixture.read_bytes()))
    owner = workspace.comms.registry.declare(Thread(
        "scroll-reader", frozenset(), Checkout(workspace.project),
        session_file=RegistrySessionLocation.from_path(journal, workspace.comms.root)))
    root = str(workspace.comms.root)
    async with workspace.app(size=size, session=False, application=recorded_app) as ui:
        await ui.app.session_navigation.new(
            MailboxTab(owner.incarnation, root),
            partial(MainScreen.from_thread, owner.worktree, root, owner.incarnation),
            original=(root, owner.incarnation))
        await ui.until(lambda: ui.conversation.transcript.reports_coverage,
                       why="the retained transcript to load", seconds=60)
        window = ui.conversation.window
        history = ui.conversation.contents.query_one(TranscriptHistory)
        await ui.until(lambda: history.pages and all(page.rows_measured for page in history.pages),
                       why="the initial retained page to be measured", seconds=60)
        screen = ui.app.screen
        screen.recording = True
        for _ in range(2048):
            await wheel(ui, window, events.MouseScrollUp)
            if len(screen.frames) > 1 and screen.frames[-1][1] > screen.frames[-2][1]:
                break
            if window.scroll_y == 0 and not history.has_more(OLDER_END):
                break
        screen.recording = False
        frames = screen.frames
        forward = [(before, after) for before, after in zip(frames, frames[1:]) if after[1] > before[1]]
        assert not forward, f"Upward inputs published forward reader movement: {forward[:3]}"


async def test_wrapped_header_pins_once_its_first_row_leaves_and_matches_the_flow(workspace):
    """A header that wraps to two rows pins as soon as one row has scrolled off, drawn as the flow draws it."""
    import gzip
    from functools import partial
    from pathlib import Path

    from agent_comms.repo import Checkout
    from agent_comms.session_file import RegistrySessionLocation
    from agent_comms.threads import Thread
    from toad.screens.main import MainScreen
    from toad.tab_identity.kinds import MailboxTab
    from toad.widgets.transcript_history import TranscriptHistory

    fixture = Path(__file__).parents[1] / "fixtures" / "laptop_scroll_shape.jsonl.gz"
    journal = workspace.project / "laptop-history.jsonl"
    journal.write_bytes(gzip.decompress(fixture.read_bytes()))
    owner = workspace.comms.registry.declare(Thread(
        "scroll-reader", frozenset(), Checkout(workspace.project),
        session_file=RegistrySessionLocation.from_path(journal, workspace.comms.root)))
    root = str(workspace.comms.root)
    async with workspace.app(size=(44, 32), session=False, application=recorded_app) as ui:
        await ui.app.session_navigation.new(
            MailboxTab(owner.incarnation, root),
            partial(MainScreen.from_thread, owner.worktree, root, owner.incarnation),
            original=(root, owner.incarnation))
        await ui.until(lambda: ui.conversation.transcript.reports_coverage,
                       why="the retained transcript to load", seconds=60)
        window = ui.conversation.window
        history = ui.conversation.contents.query_one(TranscriptHistory)
        await ui.until(lambda: history.pages and all(page.rows_measured for page in history.pages),
                       why="the initial retained page to be measured", seconds=60)
        found = None
        for page, first in window.placements(window.drawn_pages()):
            for row in range(page.line_count):
                span = page.fragment_at(row)
                if span is None or span.height < 2 or row != span.first + 1:
                    continue
                if (not span.fragment.sticky_header(span.index, 0)
                        and span.fragment.sticky_header(span.index, 1)):
                    found = page, first, span
                    break
            if found:
                break
        assert found, "No wrapped header in the drawn pages at this width"
        page, first, span = found
        window.scroll_to(y=first + span.first + 1, animate=False, immediate=True)
        await ui.step()
        sticky = window.sticky_header
        assert sticky.display, "A wrapped header with one row scrolled off did not pin"

        def text(widget, y):
            return "".join(segment.text for segment in widget.render_line(y, widget._paint_state))

        flow = [text(page, span.first + offset) for offset in range(span.height)]
        pinned = [text(sticky, offset) for offset in range(span.height)]
        assert pinned == flow, f"Pinned header {pinned} differs from the flow's {flow}"
        assert (sticky.region.x, sticky.region.width) == (page.region.x, page.region.width), (
            sticky.region, page.region)


class TopRowScreen(RecordedHistoryScreen):
    """Record the text on the window's top row in every published frame."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.top_rows: list[str] = []
        self.watching = False

    def _on_frame_published(self):
        super()._on_frame_published()
        if self.watching:
            self.top_rows.append(top_row_text(self.query_one(Conversation).window))


def top_row_text(window) -> str:
    y = window.scroll_y
    for page, first in window.placements(window.drawn_pages()):
        if first <= y < first + page.line_count:
            return "".join(segment.text for segment in page.render_line(int(y - first), page._paint_state))
    return ""


def top_row_app(*, launch_root, **kwargs):
    from toad.app import ToadApp

    app = ToadApp(launch_root=launch_root, **kwargs)
    app.remove_mode("workspace")
    app.add_mode("workspace", partial(TopRowScreen, id="workspace"))
    return app


async def test_rows_without_styling_never_move_the_reader_at_phone_width(workspace):
    """A fragment's height is its styled rows' alone: when every fragment loses its rows (a
    theme change, as an older page arriving unstyled does), the reader's top row keeps its text
    in every frame instead of showing a stand-in wrap and then snapping back."""
    import gzip
    from pathlib import Path

    from agent_comms.repo import Checkout
    from agent_comms.session_file import RegistrySessionLocation
    from agent_comms.threads import Thread
    from toad.screens.main import MainScreen
    from toad.tab_identity.kinds import MailboxTab
    from toad.widgets.transcript_history import TranscriptHistory

    fixture = Path(__file__).parents[1] / "fixtures" / "laptop_scroll_shape.jsonl.gz"
    journal = workspace.project / "laptop-history.jsonl"
    journal.write_bytes(gzip.decompress(fixture.read_bytes()))
    owner = workspace.comms.registry.declare(Thread(
        "scroll-reader", frozenset(), Checkout(workspace.project),
        session_file=RegistrySessionLocation.from_path(journal, workspace.comms.root)))
    root = str(workspace.comms.root)
    async with workspace.app(size=(63, 40), session=False, application=top_row_app) as ui:
        await ui.app.session_navigation.new(
            MailboxTab(owner.incarnation, root),
            partial(MainScreen.from_thread, owner.worktree, root, owner.incarnation),
            original=(root, owner.incarnation))
        await ui.until(lambda: ui.conversation.transcript.reports_coverage,
                       why="the retained transcript to load", seconds=60)
        window = ui.conversation.window
        history = ui.conversation.contents.query_one(TranscriptHistory)
        await ui.until(lambda: history.pages and all(page.rows_measured for page in history.pages),
                       why="the initial retained page to be measured", seconds=60)
        for _ in range(12):
            await wheel(ui, window, events.MouseScrollUp)
        await ui.step()
        top = top_row_text(window)
        assert top.strip(), "The reader's top row draws no text to keep"
        screen = ui.app.screen
        screen.watching = True
        ui.app.theme = next(name for name in ui.app.available_themes if name != ui.app.theme)
        await ui.until(lambda: all(page.rows_measured for page in history.pages),
                       why="the restyled pages to be measured", seconds=60)
        for _ in range(4):
            await ui.step()
        screen.watching = False
        moved = [row for row in screen.top_rows if row != top]
        assert not moved, (f"At width {history.pages[0].size.width} the top row {top!r} "
                           f"showed {moved[:3]} while styled rows were missing")
