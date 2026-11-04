"""Textual-facing: the window's top edge. Upward wheel travel never moves the reader forward, past live thoughts or through saved history; a wrapped message header pins the moment its first row leaves, drawn exactly as the flow draws it; at phone width the reader's top row keeps its text while saved fragments restyle and while a live thought streams."""


import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

import pytest
from textual import events

from toad.widgets.agent_response import AgentResponse
from toad.widgets.agent_thought import AgentThought

from test_scroll_down_bounce import RecordedHistoryScreen, recorded_app, wheel
from support.workspace import Workspace
from toad.widgets.conversation import Conversation
from toad.widgets.presentation_window import OLDER_END, PresentationBudget
from support.styling import awaits_styling


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
        # The reader is the painted text, not the offset: a block above the reader that
        # renders late adds rows, and the window raises scroll_y to keep the text still.
        rows = painted_markers(ui.visible_lines())
        forward = []
        for step in range(400):
            await wheel(ui, window, events.MouseScrollUp)
            painted = painted_markers(ui.visible_lines())
            forward += [(step, marker, rows[marker], painted[marker])
                        for marker in rows.keys() & painted.keys() if painted[marker] < rows[marker]]
            rows = painted
            if window.scroll_y == 0:
                break
        assert not forward, f"Upward wheel moved visible text up (step, text, row before, row after): {forward}"
        assert window.scroll_y == 0, "Upward wheel never reached the top"


MARKER = re.compile(r"(?:Earlier|Later) paragraph \d+\b|" + "|".join(map(re.escape, THOUGHTS)))


def painted_markers(lines: list[str]) -> dict[str, int]:
    """The screen row of every distinct transcript marker painted on screen."""
    return {match.group(0): row for row, line in enumerate(lines)
            for match in MARKER.finditer(line)}


@pytest.mark.parametrize("size", [(100, 32), (50, 44)])
async def test_wheel_up_through_saved_history_never_moves_forward(workspace, size):
    """The laptop's saved conversation shape: thoughts after channel messages, agent replies and tools."""
    import gzip
    from functools import partial
    from pathlib import Path

    from agent_comms.repo import Checkout
    from agent_comms.session_file import RegistrySessionLocation
    from agent_comms.threads import NativeThread
    from toad.screens.main import MainScreen
    from toad.tab_identity.kinds import MailboxTab
    from toad.widgets.transcript_history import TranscriptHistory

    fixture = Path(__file__).parents[1] / "fixtures" / "laptop_scroll_shape.jsonl.gz"
    journal = workspace.project / "laptop-history.jsonl"
    journal.write_bytes(gzip.decompress(fixture.read_bytes()))
    owner = workspace.comms.registry.declare(NativeThread(
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
    from agent_comms.threads import NativeThread
    from toad.screens.main import MainScreen
    from toad.tab_identity.kinds import MailboxTab
    from toad.widgets.transcript_history import TranscriptHistory

    fixture = Path(__file__).parents[1] / "fixtures" / "laptop_scroll_shape.jsonl.gz"
    journal = workspace.project / "laptop-history.jsonl"
    journal.write_bytes(gzip.decompress(fixture.read_bytes()))
    owner = workspace.comms.registry.declare(NativeThread(
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
    """Record the text on the window's top row in every published frame, read by `watching`."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.top_rows: list[str] = []
        self.watching: Callable[[], str] | None = None

    def _on_frame_published(self):
        super()._on_frame_published()
        if self.watching is not None:
            self.top_rows.append(self.watching())


def top_row_text(window) -> str:
    """The saved-history row drawn on the window's top row."""
    y = window.scroll_y
    for page, first in window.placements(window.drawn_pages()):
        if first <= y < first + page.line_count:
            return "".join(segment.text for segment in page.render_line(int(y - first), page._paint_state))
    return ""


def block_top_row_text(window, block) -> str:
    """The row of a live block drawn on the window's top row, when the block crosses it."""
    row = window.content_region.y - block.region.y
    if not 0 <= row < block.size.height:
        return ""
    return "".join(segment.text for segment in block.render_line(row, block._paint_state))


def top_row_app(*, connection, **kwargs):
    from toad.app import ToadApp

    app = ToadApp(connection=connection, **kwargs)
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
    from agent_comms.threads import NativeThread
    from toad.screens.main import MainScreen
    from toad.tab_identity.kinds import MailboxTab
    from toad.widgets.transcript_history import TranscriptHistory

    fixture = Path(__file__).parents[1] / "fixtures" / "laptop_scroll_shape.jsonl.gz"
    journal = workspace.project / "laptop-history.jsonl"
    journal.write_bytes(gzip.decompress(fixture.read_bytes()))
    owner = workspace.comms.registry.declare(NativeThread(
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
        screen.watching = partial(top_row_text, window)
        ui.app.theme = next(name for name in ui.app.available_themes if name != ui.app.theme)
        await ui.until(lambda: all(page.rows_measured for page in history.pages),
                       why="the restyled pages to be measured", seconds=60)
        for _ in range(4):
            await ui.step()
        screen.watching = None
        moved = [row for row in screen.top_rows if row != top]
        assert not moved, (f"At width {history.pages[0].size.width} the top row {top!r} "
                           f"showed {moved[:3]} while styled rows were missing")


THINKING = "\n\n".join((
    "### Tracing the **reader position** through `ReaderPosition.of`",
    "The window anchors on the top row's fragment, so a row that changes height above "
    "the anchor moves everything below it. `place_reader` restores the fraction, "
    "but only against the *current* height.",
    "- check `FragmentPosition.fraction` after a restyle\n- check `BlockPosition` for live rows\n"
    "- compare **plain** and **styled** wrap at `36` columns",
    "Next: the live thought itself streams while the reader sits on it, so its rows "
    "must not change as more text arrives",
))


@dataclass(frozen=True)
class ReaderReturnFrame:
    shown: bool
    row: str
    scroll: float
    position: str


@pytest.mark.parametrize("budget", (
    PresentationBudget(),
    PresentationBudget(minimum_widgets=1, widgets_per_row=0),
), ids=("warm", "budget-pressure"))
async def test_returning_to_tab_keeps_the_reader_below_a_live_thought(
    workspace: Workspace, budget: PresentationBudget,
) -> None:
    async with workspace.app(size=(63, 40), application=top_row_app) as ui:
        first = ui.selected_tab
        view = ui.conversation
        await view.post(AgentResponse("\n\n".join(f"Earlier paragraph {i}" for i in range(20))))
        thought = AgentThought(THINKING)
        await view.post(thought)
        later = AgentResponse("\n\n".join(f"RETURN_ROW_{i:03d}" for i in range(40)))
        await view.post(later)
        await ui.until(lambda: not awaits_styling(thought._styled) and not awaits_styling(later.body._styled),
                       why="both live blocks to have their actual styled rows")
        window = view.window
        window.anchor()
        await ui.until(lambda: window.max_scroll_y > 0 and window.follows_tail,
                       why="the actual rendered tail before reader input")
        await wheel(ui, window, events.MouseScrollUp)
        for _ in range(4):
            await ui.step()
            baseline = block_top_row_text(window, later.body)
            if baseline.strip():
                break
            window.action_scroll_up()
        assert baseline.strip(), "The reader must start on a painted response row"
        assert later.body.region.y < window.content_region.y < later.body.region.bottom
        assert thought.region.bottom <= window.content_region.y
        assert not window.follows_tail
        frames: list[ReaderReturnFrame] = []

        def observe() -> str:
            row = block_top_row_text(window, later.body)
            frames.append(ReaderReturnFrame(window.shown, row, window.scroll_y, repr(window.reader_position)))
            return row

        screen = ui.app.screen
        screen.watching = observe
        try:
            await ui.new_session()
            # Exercise the actual resource policy with its admitted budget, not
            # fabricated widget costs or a replacement eviction method.
            ui.conversation.window.presentation_budget = budget
            await ui.app.workspace_chrome.native.reconcile(ui.app.selected_session)
            await ui.select_tab(first)
            assert ui.conversation is view, "A native reader requires its original tree"
            for _ in range(4):
                await ui.step()
            visible = [frame for frame in frames if frame.shown]
            assert visible, "Returning must publish the retained reader"
            assert all(frame.row == baseline for frame in visible), (baseline, visible)
            assert ui.failure() is None
        finally:
            screen.watching = None


async def test_a_live_thought_crossing_the_top_edge_keeps_its_rows_at_phone_width(workspace):
    """A live thought's height is its styled rows' alone: while it streams with the reader on
    one of its rows at the top edge, that row keeps its text in every frame instead of
    switching to a plain stand-in wrap and back."""
    async with workspace.app(size=(63, 40), application=top_row_app) as ui:
        view = ui.conversation
        await view.post(AgentResponse("\n\n".join(f"Earlier paragraph {i}" for i in range(20))))
        thought = AgentThought(THINKING)
        await view.post(thought)
        await view.post(AgentResponse("\n\n".join(f"Later paragraph {i}" for i in range(20))))
        await ui.until(lambda: not awaits_styling(thought._styled), why="the thought's styled rows")
        window = view.window
        window.anchor()
        await ui.until(lambda: window.max_scroll_y > 0 and window.follows_tail, why="a scrollable tail")
        for _ in range(400):
            if thought.region.y + 2 < window.content_region.y < thought.region.bottom - 6:
                break
            await wheel(ui, window, events.MouseScrollUp)
        await ui.step()
        top = block_top_row_text(window, thought)
        assert top.strip(), f"The thought never crossed the top edge at width {thought.size.width}"
        screen = ui.app.screen
        screen.watching = partial(block_top_row_text, window, thought)
        for chunk in (" and", " then a few more", " words arrive", " in the last paragraph"):
            thought.append(chunk)
            await ui.step()
        await ui.until(lambda: thought._render_worker.is_finished,
                       why="the streamed text to be styled")
        for _ in range(4):
            await ui.step()
        screen.watching = None
        moved = [row for row in screen.top_rows if row != top]
        assert not moved, (f"At width {thought.size.width} the thought's top row {top!r} "
                           f"showed {moved[:3]} while its text streamed")
