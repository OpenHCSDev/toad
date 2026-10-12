"""Textual-facing: the row the reader is on stays where it is drawn through every change to what the history window draws.

One history window owns where the reader is. Each test puts the reader somewhere (the rows of the matrix), changes
what is drawn (the columns) and reads the painted screen: the first written line in the window and the row it is on.

The rule every cell checks:
- a reader following the latest message still follows it;
- otherwise the line the reader had at the top is on the same row, when the change still shows that line;
- when the change hides that line's message, the next message still shown starts at the top;
- End goes to the latest message; closing or quitting part-way through a change ends without an error.

The saved history is a paged fixture read through the history's own loader; nothing in Toad is replaced.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import re
import threading
from unittest.mock import patch

import pytest

from agent_comms.transcript_events import AssistantTranscript, ThinkingTranscript
from agent_comms.transcripts import TranscriptCursor, TranscriptPage

from toad.widgets.agent_response import AgentResponse
from toad.widgets.message_filter import AgentCategory, ThinkingCategory, all_categories
from toad.widgets.presentation_window import PresentationBudget
from toad.widgets.transcript_history import TranscriptHistory

FILE = "paged-fixture"
# More pages than are ever read ahead of a reader: a cell that needs a read still running can travel to one.
PAGES = 40
PER_PAGE = 8
WRITTEN = re.compile(r"(ANSWER|THINK) (\d+)\.(\d+)\b(?!\.)|(item|thought) (\d+)\.(\d+)\.(\d+)")
NO_THINKING = all_categories() - {ThinkingCategory}
NO_ANSWERS = all_categories() - {AgentCategory}
ONLY_THINKING = frozenset({ThinkingCategory})


def page(number: int) -> TranscriptPage:
    """Eight messages: answers at even places, thinking at odd places, each a title, five rows and a wide row.

    The wide row fits the window at the starting size and wraps when the resize makes the window narrower.
    """
    wide = "\n- " + "wide " * 11
    events = tuple(
        ThinkingTranscript(f"THINK {number}.{index}\n\n" + "\n".join(
            f"- thought {number}.{index}.{row}" for row in range(5)) + wide)
        if index % 2 else
        AssistantTranscript(f"ANSWER {number}.{index}\n\n" + "\n".join(
            f"- item {number}.{index}.{row}" for row in range(5)) + wide)
        for index in range(PER_PAGE))
    return TranscriptPage(events, TranscriptCursor(FILE, number * 100), TranscriptCursor(FILE, (number + 1) * 100),
                          number > 0, number < PAGES - 1)


@dataclass(frozen=True)
class Line:
    """One written line of the fixture as drawn: its text, its row in the window and its place in the history."""

    text: str
    row: int
    message: tuple[int, int]
    thinking: bool
    title: bool


@dataclass
class Reader:
    """The running app with the paged history, and the questions the cells ask of its screen."""

    ui: object
    history: TranscriptHistory = None
    reads_held: asyncio.Event = field(default_factory=asyncio.Event)
    later_reads_held: asyncio.Event = field(default_factory=asyncio.Event)
    reads_waiting: int = 0

    def __post_init__(self):
        self.reads_held.set()
        self.later_reads_held.set()

    async def load(self, before=None, after=None, **_):
        self.reads_waiting += 1
        try:
            await self.reads_held.wait()
            if after is not None:
                await self.later_reads_held.wait()
        finally:
            self.reads_waiting -= 1
        return page(before.offset // 100 - 1) if before is not None else page(after.offset // 100)

    @property
    def window(self):
        return self.ui.conversation.window

    def idle(self) -> bool:
        """Nothing is laid out or put back, and nothing is read but what a cell holds: the window keeps what it draws."""
        screen, history = self.window.screen, self.history
        reading = history.is_attached and not (history.state.accepts_source_work and not history.filter.scanning)
        return (screen._stepped_layout is None and not screen._layout_required
                and (not reading or self.reads_waiting > 0))

    def drawn(self) -> bool:
        """The first pages are drawn in full, with more than two windows of rows above the latest message.

        A reader who travels up before that stands on the newest rows, where hiding a kind of message leaves
        less than a window of rows below them and no window can keep their line on its row.
        """
        window = self.window
        return self.history.is_mounted and self.idle() and window.max_scroll_y >= 2 * window.size.height

    def lines(self) -> list[Line]:
        region = self.window.region
        found = []
        for row, text in enumerate(self.ui.visible_lines()[region.y:region.bottom]):
            if (match := WRITTEN.search(text)) is not None:
                title, title_page, title_index, kind, row_page, row_index, _ = match.groups()
                message = (int(title_page or row_page), int(title_index or row_index))
                found.append(Line(match.group(0), row, message, (title or kind) in ("THINK", "thought"), bool(title)))
        return found

    def top(self) -> Line | None:
        return next(iter(self.lines()), None)

    async def settled(self) -> Line | None:
        """Wait until nothing is at work and the window draws the same thing three times running."""
        _app, pilot = self.ui.textual
        seen, same, samples = object(), 0, []
        try:
            async with asyncio.timeout(20):
                while same < 3:
                    await pilot.wait_for_scheduled_animations()
                    await self.ui.step(0.15)
                    now = (self.top(), self.window.scroll_y, self.window.max_scroll_y)
                    samples.append(now)
                    seen, same = now, same + 1 if now == seen and self.idle() else 0
        except TimeoutError:
            raise AssertionError(f"the window kept changing; last samples: {samples[-8:]}") from None
        return self.top()

    async def keys(self, key: str, count: int) -> None:
        _app, pilot = self.ui.textual
        for _ in range(count):
            await self.ui.press(key)
            await pilot.wait_for_scheduled_animations()
            await self.ui.step(0.05)

    async def seek(self, wanted, row: int = 0) -> None:
        """Press Up until the first written line in the window is on `row` and is one `wanted` accepts."""
        for _ in range(120):
            top = self.top()
            if top is not None and top.row == row and wanted(top):
                return
            await self.keys("up", 1)
        raise AssertionError(f"no such line reached the top; screen:\n{self.ui.visible_text()}")


# Where the reader is (matrix rows). `thinking` says which kind of message the reader stands on.

async def at_bottom(reader: Reader, thinking: bool) -> None:
    assert reader.window.follows_tail


async def mid_page(reader: Reader, thinking: bool) -> None:
    await reader.keys("pageup", 5)
    await reader.seek(lambda line: line.thinking is thinking and not line.title)


async def page_boundary(reader: Reader, thinking: bool) -> None:
    await reader.keys("pageup", 5)
    # A page starts with the divider row above its first message's title.
    await reader.seek(lambda line: line.title and line.message[1] == 0, row=1)


async def on_hidden_row(reader: Reader, thinking: bool) -> None:
    await reader.keys("pageup", 5)
    await reader.seek(lambda line: line.thinking is thinking and not line.title)


async def with_selection(reader: Reader, thinking: bool) -> None:
    await mid_page(reader, thinking)
    app, pilot = reader.ui.textual
    await pilot.mouse_down(reader.window, offset=(6, 6))
    await pilot.hover(reader.window, offset=(18, 9))
    await pilot.mouse_up(reader.window, offset=(18, 9))
    await reader.ui.step()
    assert app.screen.get_selected_text(), "nothing was selected"


STATES = {"at-bottom": at_bottom, "mid-page": mid_page, "page-boundary": page_boundary,
          "on-hidden-row": on_hidden_row, "with-selection": with_selection, "held-pageup": mid_page}


# What changes (matrix columns).

@dataclass(frozen=True)
class Change:
    act: object
    before: object = None            # runs before the reader takes its place
    before_hides_thinking: bool = False  # `before` leaves only answers to stand on
    hides_thinking: bool | None = None   # which kind the change hides; None hides nothing
    expect: str = "kept"             # "kept", "latest" or "ends"
    budget: PresentationBudget | None = None


def choose(selected):
    async def act(reader: Reader):
        reader.ui.conversation.visible_categories = selected
    return act


async def reapply(reader: Reader):
    for selected in (NO_THINKING, all_categories(), NO_THINKING):
        reader.ui.conversation.visible_categories = selected
        # A reader holding PageUp keeps the window moving: each choice is laid out, not stood still on.
        await reader.ui.step()
        await reader.ui.until(reader.idle, why="the chosen kinds laid out")


async def older_page_loads(reader: Reader):
    """Travel up to the first row drawn while the earlier page is still being read, then let the read finish.

    Pages are read ahead of the reader and added when the reader nears them, so only at the top of what is
    drawn does a finished read add its page above the reader at once.
    """
    reader.reads_held.clear()
    for _ in range(PAGES * 4):
        if reader.reads_waiting and reader.window.scroll_y == 0:
            break
        await reader.keys("pageup", 1)
    assert reader.reads_waiting and reader.window.scroll_y == 0, (
        "the reader did not reach a page still being read", reader.reads_waiting, reader.window.scroll_y,
        reader.history.has_older, [page.capture_range() for page in reader.history.pages])
    await reader.settled()
    first = reader.history.pages[0]
    start = reader.top()
    reader.reads_held.set()
    await reader.ui.until(lambda: reader.history.pages[0] is not first, why="the earlier page to be added")
    return start


async def rows_above_are_trimmed(reader: Reader):
    """Go far up, then down to the last row drawn while the later page is still being read, then let it finish.

    Going up drops the latest pages; adding one back below the reader removes the earliest rows, above them.
    """
    # A later page is read ahead as soon as one is dropped: hold those reads from the start, so the page
    # is still being read when the reader comes back down to the last row drawn.
    reader.later_reads_held.clear()
    await reader.keys("pageup", 14)
    for _ in range(30):
        if reader.history.has_newer:
            break
        await reader.keys("pageup", 1)
    assert reader.history.has_newer, "going up did not drop the latest pages"
    await reader.settled()
    for _ in range(60):
        if reader.reads_waiting and reader.window.scroll_y == reader.window.max_scroll_y:
            break
        await reader.keys("pagedown", 1)
    assert reader.reads_waiting and reader.history.has_newer, (
        "the reader did not reach a later page still being read", reader.reads_waiting, reader.window.scroll_y,
        reader.window.max_scroll_y, reader.history.has_newer,
        [page.capture_range() for page in reader.history.pages])
    await reader.settled()
    first = reader.history.pages[0], reader.history.pages[0].start
    start = reader.top()
    reader.later_reads_held.set()
    await reader.ui.until(lambda: (reader.history.pages[0], reader.history.pages[0].start) != first,
                          why="the earliest rows to be trimmed")
    return start


async def new_message(reader: Reader):
    await reader.ui.conversation.post(AgentResponse("NEW MESSAGE\n\n" + "\n".join(f"- new {row}" for row in range(6))))


async def tab_hidden_and_shown(reader: Reader):
    first = reader.ui.selected_tab
    await reader.ui.new_session()
    await reader.ui.step(0.3)
    await reader.ui.select_tab(first)


async def resize(reader: Reader):
    await reader.ui.resize(96, 31)


async def change_theme(reader: Reader):
    """Every line is drawn again in the new colours: plain rows first, the styled rows when they are ready."""
    app, _pilot = reader.ui.textual
    app.theme = "ansi-light" if app.theme != "ansi-light" else "ansi-dark"


async def end_key(reader: Reader):
    await reader.ui.press("end")


async def open_second_tab(reader: Reader):
    first = reader.ui.selected_tab
    await reader.ui.new_session()
    await reader.ui.select_tab(first)


async def close_tab_mid_change(reader: Reader):
    first = reader.ui.selected_tab
    reader.ui.conversation.visible_categories = NO_THINKING
    await reader.ui.close_tab(first)
    await reader.ui.step(0.5)
    assert reader.ui.selected_tab != first


async def quit_mid_change(reader: Reader):
    app, _pilot = reader.ui.textual
    reader.ui.conversation.visible_categories = NO_THINKING
    app.exit()
    await reader.ui.step(0.5)


CHANGES = {
    "apply-filter": Change(choose(NO_THINKING), hides_thinking=True),
    "clear-filter": Change(choose(all_categories()), before=choose(NO_THINKING), before_hides_thinking=True),
    "change-filter": Change(choose(NO_ANSWERS), before=choose(NO_THINKING), before_hides_thinking=True,
                            hides_thinking=False),
    "reapply-filter": Change(reapply, hides_thinking=True),
    "narrow-filter": Change(choose(ONLY_THINKING), hides_thinking=False),
    "older-page-loads": Change(older_page_loads),
    "new-message": Change(new_message),
    # Enough messages for the window and the rows read ahead on both sides, few enough that going up drops
    # the latest pages (the default keeps every page: open defect history-admission-growth).
    "rows-above-trimmed": Change(rows_above_are_trimmed, budget=PresentationBudget(max_items=32)),
    "tab-hidden-and-shown": Change(tab_hidden_and_shown),
    "resize": Change(resize),
    "theme": Change(change_theme),
    "end": Change(end_key, expect="latest"),
    "close-tab": Change(close_tab_mid_change, before=open_second_tab, expect="ends"),
    "quit": Change(quit_mid_change, expect="ends"),
}


def next_shown(message: tuple[int, int]) -> tuple[int, int]:
    """The message after `message`: kinds alternate, so it is the nearest one a one-kind filter still shows."""
    number, index = message
    return (number, index + 1) if index + 1 < PER_PAGE else (number + 1, 0)


async def hold_pageup(reader: Reader, stop: asyncio.Event) -> None:
    while not stop.is_set():
        await reader.ui.press("pageup")
        await asyncio.sleep(0.03)


# Holding PageUp while the trim change itself travels down is not a state a reader can be in.
CELLS = [pytest.param(state, change, id=f"{state}-{change}") for state in STATES for change in CHANGES
         if (state, change) != ("held-pageup", "rows-above-trimmed")]


@pytest.mark.parametrize("state_name, change_name", CELLS)
async def test_the_reader_keeps_its_place(workspace, state_name, change_name):
    change = CHANGES[change_name]
    async with workspace.app(size=(110, 40)) as ui:
        reader = Reader(ui)
        reader.history = await ui.conversation.post(
            TranscriptHistory(page(PAGES - 1), loader=reader.load, budget=change.budget))
        window = reader.window
        await ui.until(reader.drawn, why="the history drawn")
        if change.before is not None:
            await change.before(reader)
            await reader.settled()
        window.focus(scroll_visible=False)
        # The reader takes its place on a line of the kind the change hides, or of the other kind.
        hidden_kind = bool(change.hides_thinking)
        on_hidden = state_name == "on-hidden-row" and change.hides_thinking is not None
        thinking = hidden_kind if on_hidden else not hidden_kind
        await STATES[state_name](reader, thinking and not change.before_hides_thinking)
        start = await reader.settled()
        following = window.follows_tail

        held = state_name == "held-pageup"
        stop = asyncio.Event()
        holding = asyncio.create_task(hold_pageup(reader, stop)) if held else None
        try:
            moved = await change.act(reader)
        finally:
            stop.set()
            if holding is not None:
                await holding
        if change.expect == "ends":
            assert ui.failure() is None
            return
        if moved is not None:
            # The change moved the reader into the history before it changed what is drawn.
            start, following = moved, False
        end = await reader.settled()
        assert ui.failure() is None

        if change.expect == "latest" or following:
            assert window.follows_tail and window.scroll_y == window.max_scroll_y, "the reader left the latest message"
            return
        assert start is not None and end is not None, f"no written line at the top; screen:\n{ui.visible_text()}"
        if held:
            # The reader was travelling up: the change may not throw them further down the history.
            assert end.message <= next_shown(start.message), (start, end)
            return
        assert not window.follows_tail, "a reader inside the history was sent to the latest message"
        hides = change.hides_thinking is not None and start.thinking is change.hides_thinking
        if hides:
            assert end.message == next_shown(start.message) and end.title and end.row <= 2, (start, end)
        else:
            assert (end.text, end.row) == (start.text, start.row), (start, end)


async def test_unticking_message_kinds_in_the_sidebar_while_scrolled_up_keeps_toad_running(workspace):
    """The reported crash: scrolled up in a long history, untick and tick message kinds in the thread sidebar."""
    from textual.widgets import Checkbox
    from toad.widgets.side_bar import SideBar

    async with workspace.app(size=(150, 45)) as ui:
        app, pilot = ui.textual
        reader = Reader(ui)
        reader.history = await ui.conversation.post(TranscriptHistory(page(PAGES - 1), loader=reader.load))
        window = reader.window
        await ui.until(reader.drawn, why="the history drawn")
        sidebar = app.screen.query_one("#thread-sidebar", SideBar)
        sidebar.reveal()
        await sidebar.wait_content_ready()
        boxes = {str(box.label): box for box in sidebar.query(Checkbox)}
        thinking, agent = boxes["Thinking"], boxes["Agent messages"]
        await ui.until(lambda: thinking.display and thinking.region.height > 0, why="the filter boxes drawn")
        window.focus(scroll_visible=False)
        await reader.keys("pageup", 12)
        await reader.settled()
        for box in (thinking, agent, thinking, agent, thinking, thinking):
            box.scroll_visible(animate=False, immediate=True)
            await ui.step()
            assert await pilot.click(box)
            await reader.settled()
            assert ui.failure() is None and app.is_running, "Toad stopped"
        assert ui.conversation.visible_categories == all_categories()
        assert not window.follows_tail and reader.top() is not None


CHANNEL_HEAD = re.compile(r"Message (\d+):")


def channel_top(ui, window) -> tuple[str, int] | None:
    """The first message whose opening line is drawn in the channel window, and the row it is on."""
    region = window.region
    for row, text in enumerate(ui.visible_lines()[region.y:region.bottom]):
        if (match := CHANNEL_HEAD.search(text)) is not None:
            return match.group(0), row
    return None


async def channel_settled(ui, window) -> tuple[str, int] | None:
    _app, pilot = ui.textual
    seen, same = object(), 0
    async with asyncio.timeout(20):
        while same < 3:
            await pilot.wait_for_scheduled_animations()
            await ui.step(0.15)
            now = (channel_top(ui, window), window.scroll_y, window.max_scroll_y)
            laid_out = window.screen._stepped_layout is None and not window.screen._layout_required
            seen, same = now, same + 1 if now == seen and laid_out else 0
    return channel_top(ui, window)


@pytest.mark.parametrize("change", ["older-page-loads", "new-message", "tab-hidden-and-shown", "resize", "theme"])
async def test_a_channel_reader_keeps_its_place(workspace, change):
    """A channel is drawn by the same line history: the message at the top of the window stays there."""
    from support.textual_steps import refresh_chat
    from toad.widgets.comms_chat import CommsChatView

    workspace.thread("sender", "scroll", running=True)
    for index in range(140):
        workspace.comms.messaging.send("sender", "#scroll", f"Message {index}: " + "wrapped body " * 30)
    # A channel reads every earlier page ahead while nothing else happens: only the first two are let
    # through, so that the older-page case still has a page to be read when its reader is at the top.
    earlier_reads_held, earlier, waiting = threading.Event(), [], []
    if change != "older-page-loads":
        earlier_reads_held.set()
    async with workspace.app(size=(110, 38)) as ui:
        app, _pilot = ui.textual
        views = app.coordination_access.service.views
        read = views.channel_display_page

        def held(target, **bounds):
            # The real read of an earlier page, started when the cell lets it.
            if bounds.get("before") is not None:
                earlier.append(bounds)
                if len(earlier) > 2 and not earlier_reads_held.is_set():
                    waiting.append(bounds)
                    earlier_reads_held.wait(30)
            return read(target, **bounds)

        # This app's own Core views, discarded with it.
        patch.object(views, "channel_display_page", side_effect=held).start()
        tab = await ui.open_channel("#scroll", actor="sender")
        chat = app.screen.query_one(CommsChatView)
        history, window = chat.message_history, chat.window
        await ui.until(lambda: history.messages and history.state.accepts_source_work and window.max_scroll_y > 12,
                       why="the channel's messages drawn")
        await channel_settled(ui, window)
        # Go up until a message's opening line is the window's first row.
        for y in range(int(window.max_scroll_y) - 6, 0, -1):
            window.scroll_to(y=y, animate=False, immediate=True)
            await ui.step()
            if (top := channel_top(ui, window)) is not None and top[1] == 0:
                break
        start = await channel_settled(ui, window)
        assert start is not None and start[1] == 0 and not window.follows_tail, start
        if change == "older-page-loads":
            # Earlier pages are read ahead of the reader. Go to the first row drawn until the page above it
            # is one still being read, so that it is added above a reader who is standing there.
            for _ in range(40):
                if waiting and window.scroll_y <= 1:
                    break
                window.scroll_to(y=1, animate=False, immediate=True)
                await ui.step(0.2)
            assert waiting and window.scroll_y <= 1, "the reader did not reach a page still being read"
            start = await channel_settled(ui, window)
            oldest = history.messages[0].seq
            earlier_reads_held.set()
            await ui.until(lambda: history.messages[0].seq < oldest and history.state.accepts_source_work,
                           why="an earlier page drawn above")
            # The page was added above the reader while they were at the top: they are not thrown to its start.
            assert window.scroll_y > 1, "the earlier page pushed the reader's rows down"
        elif change == "new-message":
            workspace.comms.messaging.send("sender", "#scroll", "ARRIVED-WHILE-READING")
            await refresh_chat(chat)
        elif change == "tab-hidden-and-shown":
            await ui.new_session()
            await ui.step(0.3)
            await ui.select_tab(tab)
        elif change == "resize":
            await ui.resize(96, 31)
        else:
            app.theme = "ansi-light" if app.theme != "ansi-light" else "ansi-dark"
        end = await channel_settled(ui, window)
        assert ui.failure() is None and app.is_running, "Toad stopped"
        assert not window.follows_tail, "a reader inside the channel's history was sent to the latest message"
        if start is not None:
            assert end == start, (start, end)
