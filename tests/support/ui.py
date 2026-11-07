"""The questions a test asks the running interface, whichever toolkit draws it.

A test that needs only these questions says nothing about Textual and keeps its
meaning when another frontend answers them. A test of paint, layout or widget
internals asks for ``ui.textual`` instead and lives under ``tests/textual``.
"""

from __future__ import annotations

from toad.widgets.side_bar import BackTabButton, ForwardTabButton
from toad.session_actions import ReturnToViewAction

import asyncio
from contextlib import contextmanager
import inspect
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from textual.actions import StyleAction
from textual.errors import NoWidget
from textual.geometry import Offset

from rich.cells import cell_len
from support.agents import AppAgents, command
from toad import paths
from toad.navigation_context import NavigationContext

if TYPE_CHECKING:
    from textual.pilot import Pilot

    from toad.app import ToadApp
    from toad.line_blocks import Divider, LineLink
    from toad.tab_identity.kinds import AcpTab


async def saved_tab(app: ToadApp) -> AcpTab:
    """A test-made native session is saved the way launch saves one, with the app's agent;
    a session with no agent saves an inert one."""
    from toad.launch_binding import AgentAttached

    binding = app.agent_binding
    agent = (binding.agent if isinstance(binding, AgentAttached)
             else command("true", name="Test session", identity="test-session"))
    return await app.session_navigation.saved(agent, app.project_dir)


class NotShown(AssertionError):
    """The screen never showed what the test waited for; carries the last screen."""


class ReportedError(AssertionError):
    """The app caught an error, showed it and saved its traceback while the test expected none."""


class ErrorExpectation(ABC):
    """Whether an error the app saves right now is the test's failure."""

    @abstractmethod
    def unexpected(self, ui: "TextualUi") -> ReportedError | None: ...


@dataclass(frozen=True)
class RefusesErrors(ErrorExpectation):
    """The default: the first saved error not acknowledged ends the wait with its traceback."""

    acknowledged: frozenset[Path] = frozenset()

    def unexpected(self, ui: "TextualUi") -> ReportedError | None:
        for path in ui.reported_errors():
            if path not in self.acknowledged:
                return ReportedError(f"the app reported {path.name}:\n{path.read_text()}")
        return None


class ExpectsErrors(ErrorExpectation):
    """Inside `reporting_error()`: the test shows an error on purpose and waits for it."""

    def unexpected(self, ui: "TextualUi") -> ReportedError | None:
        return None


@dataclass(frozen=True)
class Tab:
    """One open tab as the user reads it."""

    identity: str
    title: str


class Ui(ABC):
    """A running Toad interface."""

    @abstractmethod
    def visible_lines(self) -> list[str]:
        """The text of every row on screen, top to bottom."""

    @abstractmethod
    def tabs(self) -> tuple[Tab, ...]:
        """The open tabs, in the order they are drawn."""

    @property
    @abstractmethod
    def selected_tab(self) -> str:
        """The identity of the tab whose content is shown."""

    @abstractmethod
    def focused(self) -> str:
        """The name of the control that receives keys."""

    @abstractmethod
    def draft(self) -> str:
        """The text in the selected conversation's input box."""

    @abstractmethod
    async def write_draft(self, text: str) -> None:
        """Replace the selected conversation's input text and focus it."""

    @abstractmethod
    def attach_agent(self, agent) -> None:
        """Show `agent` (see ``AppAgents.detached_agent``) in the selected conversation."""

    @abstractmethod
    def status(self) -> str:
        """The selected conversation's status line."""

    @abstractmethod
    def agent_ready(self) -> bool:
        """Whether the selected conversation's agent accepts input."""

    @abstractmethod
    def selected_agent(self):
        """The agent behind the selected conversation; it keeps answering while its tab is hidden."""

    @abstractmethod
    async def press(self, *keys: str) -> None: ...

    @abstractmethod
    async def click(self, text: str, *, occurrence: int = 0) -> None:
        """Click the first cell of `text` where it is drawn on screen."""

    @abstractmethod
    def link_at(self, text: str, *, occurrence: int = 0) -> StyleAction | None:
        """The action a click on `text` would run, if it is a link."""

    @abstractmethod
    def hyperlink_at(self, text: str, *, occurrence: int = 0) -> str | None:
        """The address a click on `text` would open, if the drawn text is a hyperlink."""

    @abstractmethod
    async def resize(self, width: int, height: int) -> None: ...

    @abstractmethod
    async def select_tab(self, identity: str) -> None: ...

    @abstractmethod
    async def close_tab(self, identity: str) -> None: ...

    @abstractmethod
    async def new_session(self) -> str:
        """Open another session tab on the project and return its identity."""

    @abstractmethod
    async def open_channel(
        self, target: str, *, actor: str, owner: str | None = None
    ) -> str:
        """Open a channel or direct-message tab for `actor` and return its identity."""

    @abstractmethod
    async def open_direct(
        self, thread: str, *, actor: str, owner: str | None = None
    ) -> str:
        """Open the direct-message history between `actor` and `thread` and return its tab identity."""

    @abstractmethod
    async def return_to_owner(self) -> None:
        """From a channel or direct-message tab, go back to the session tab that opened it."""

    @abstractmethod
    async def go_back(self) -> None:
        """Step back through the visited tabs, as the Back control does."""

    @abstractmethod
    async def go_forward(self) -> None:
        """Step forward through the visited tabs, as the Forward control does."""

    @abstractmethod
    def can_go_back(self) -> bool:
        """Whether the Back control has an earlier visited tab to go to."""

    @abstractmethod
    def can_go_forward(self) -> bool:
        """Whether the Forward control has a later visited tab to go to."""

    @abstractmethod
    async def open_preview(self, path) -> str:
        """Open a file preview tab for `path` and return its tab identity."""

    @abstractmethod
    async def thread_renamed(self, owner: str, previous: str, current: str) -> None:
        """Tell the interface that the thread behind session tab `owner` was renamed on the wire."""

    @abstractmethod
    async def step(self, seconds: float | None = None) -> None:
        """Let the interface handle what is pending."""

    @property
    @abstractmethod
    def core_service(self):
        """The Core service the running interface itself reads through."""

    @abstractmethod
    def failure(self) -> BaseException | None:
        """An exception the interface caught while running, if any."""

    @abstractmethod
    def reported_errors(self) -> list[Path]:
        """Tracebacks of errors the interface caught, showed and saved instead of raising."""

    def visible_text(self) -> str:
        return "\n".join(self.visible_lines())

    def shows(self, text: str) -> bool:
        return text in self.visible_text()

    async def type(self, text: str) -> None:
        await self.press(*("space" if char == " " else char for char in text))

    async def until(
        self, condition: Callable[[], object], *, seconds: float = 10, why: str = ""
    ) -> None:
        """Wait until `condition()` is true (it may be a coroutine function)."""
        try:
            async with asyncio.timeout(seconds):
                while True:
                    if failure := self.failure():
                        raise failure
                    result = condition()
                    if inspect.isawaitable(result):
                        result = await result
                    if result:
                        return
                    await self.step(0.02)
        except TimeoutError:
            reported = "".join(f"\nerror the app reported, {path.name}:\n{path.read_text()}"
                               for path in self.reported_errors())
            raise NotShown(
                f"{why or 'condition'} not reached in {seconds}s; screen:\n{self.visible_text()}{reported}"
            ) from None

    async def until_agent_ready(self, *, seconds: float = 30) -> None:
        await self.until(
            self.agent_ready, seconds=seconds, why="the agent to accept input"
        )

    async def until_shows(self, text: str, *, seconds: float = 10) -> None:
        await self.until(
            lambda: self.shows(text), seconds=seconds, why=f"{text!r} on screen"
        )

    async def until_delivery_shown(self) -> None:
        """A sent message's delivery status arrives from Core after its rows and lifts the
        bottom-anchored page; a click aimed at the message waits for it."""
        await self.until_shows("Sent · Observed")


class TextualUi(AppAgents, Ui):
    """Toad drawn by Textual, driven headless through Textual's pilot; its agents attach to that app."""

    def __init__(self, app: ToadApp, pilot: Pilot) -> None:
        super().__init__(app)
        self.pilot = pilot
        self.errors: ErrorExpectation = RefusesErrors()

    @property
    def textual(self) -> tuple[ToadApp, Pilot]:
        """The Textual app and pilot, for tests of Textual-owned behaviour only."""
        return self.app, self.pilot

    def visible_lines(self) -> list[str]:
        return [strip.text for strip in self.app.screen._compositor.render_strips()]

    def clickable(self, widget, offset: tuple[int, int] = (0, 0)) -> bool:
        """Whether a click at `offset` in `widget` reaches it: a click lands on what the
        published frame shows there, which a newly pushed or moving widget may not be yet."""
        if not widget.is_attached:
            return False
        region, screen = widget.region, widget.screen
        point = Offset(region.x + offset[0], region.y + offset[1])
        if point not in region or point not in screen.size.region:
            return False
        try:
            return screen.get_widget_at(*point)[0] is widget
        except NoWidget:
            # A screen pushed since the last frame has none of its widgets placed yet.
            return False

    async def until_clickable(self, widget, offset: tuple[int, int] = (0, 0), *, why: str) -> None:
        await self.until(lambda: self.clickable(widget, offset), why=why)

    async def menu(self, why: str) -> dict:
        """The open context menu's actions and their labels, once it shows."""
        from toad.widgets.comms_menu import ContextMenu

        await self.until(lambda: isinstance(self.app.screen, ContextMenu) and self.app.screen.options.option_count > 0,
                         why=why)
        return {item.action: str(item.prompt) for item in self.app.screen.options.options}

    async def choose_menu_action(self, action) -> None:
        """Choose one action of the open context menu the way a keyboard user does."""
        options = self.app.screen.options
        options.highlighted = [item.action for item in options.options].index(action)
        await self.pilot.press("enter")

    def tabs(self) -> tuple[Tab, ...]:
        from toad.widgets.session_tabs import SessionLabel, SessionsTabs

        return tuple(
            Tab(label.id, label.render().plain)
            for label in self.app.screen.query_one(SessionsTabs).query(SessionLabel)
        )

    @property
    def selected_tab(self) -> str:
        return self.app.selected_mode

    def focused(self) -> str:
        widget = self.app.focused
        return "" if widget is None else (widget.id or type(widget).__name__)

    @property
    def conversation(self):
        """The selected session's conversation widget."""
        from toad.widgets.conversation import Conversation

        return self.app.selected_session.query_one(Conversation)

    def painted(self, widget) -> str:
        """The text drawn inside one widget's region of the screen."""
        region = widget.region
        return "\n".join(
            strip.crop(region.x, region.right).text
            for strip in self.app.screen._compositor.render_strips()[
                region.y : region.bottom
            ]
        )

    @property
    def _prompt(self):
        from toad.widgets.prompt import Prompt

        return self.app.selected_session.query_one(Prompt)

    def draft(self) -> str:
        return self._prompt.text

    async def write_draft(self, text: str) -> None:
        self._prompt.text = text
        self._prompt.focus()
        await self.step()

    def attach_agent(self, agent) -> None:
        self.conversation.bind_agent(agent)

    def status(self) -> str:
        return self.conversation.status.plain

    def agent_ready(self) -> bool:
        return self._prompt.agent_ready

    def selected_agent(self):
        return self.conversation.agent_binding

    async def press(self, *keys: str) -> None:
        await self.pilot.press(*keys)
        await self.step()

    def _cell_of(self, text: str, occurrence: int) -> tuple[int, int]:
        """The screen cell where the nth drawn `text` starts."""
        places = [
            (cell_len(line[: line.find(text)]), y)
            for y, line in enumerate(self.visible_lines())
            if text in line
        ]
        if len(places) <= occurrence:
            raise NotShown(f"{text!r} is not on screen:\n{self.visible_text()}")
        return places[occurrence]

    def link_cell(self, header: Divider, link: LineLink, *, occurrence: int = 0) -> tuple[int, int]:
        """Find a linked span using the header owner's text and span order."""
        x, y = self._cell_of(header.label, occurrence)
        for span in header.spans:
            if span.link == link:
                return x, y
            x += cell_len(span.text)
        raise NotShown(f"{link!r} is not in the header {header.label!r}")

    async def click(self, text: str, *, occurrence: int = 0) -> None:
        assert await self.pilot.click(
            offset=self._cell_of(text, occurrence)
        ), f"the click on {text!r} left the screen"
        await self.step()

    def link_at(self, text: str, *, occurrence: int = 0) -> StyleAction | None:
        return self.app.screen.get_style_at(*self._cell_of(text, occurrence)).meta.get(
            "@click"
        )

    def hyperlink_at(self, text: str, *, occurrence: int = 0) -> str | None:
        return self.app.screen.get_style_at(*self._cell_of(text, occurrence)).link

    async def resize(self, width: int, height: int) -> None:
        await self.pilot.resize_terminal(width, height)
        await self.step()

    async def select_tab(self, identity: str) -> None:
        await self.app.select_session(identity)
        await self.step()

    async def close_tab(self, identity: str) -> None:
        await self.app.session_navigation.close(identity)
        await self.step()

    async def new_session(self) -> str:
        from toad.screens.main import MainScreen

        app = self.app
        details = await app.session_navigation.new(
            await saved_tab(app), lambda: MainScreen(app.project_dir, app.agent_binding)
        )
        await self.step()
        return details.mode_name

    async def open_channel(
        self, target: str, *, actor: str, owner: str | None = None
    ) -> str:
        from toad.navigation_target import channel_target

        context = NavigationContext(
            self.app, owner or self.selected_tab, self.app.project_dir, actor
        )
        identity = await channel_target(target).open(context)
        await self.step()
        return identity

    async def open_direct(
        self, thread: str, *, actor: str, owner: str | None = None
    ) -> str:
        from toad.navigation_target import DirectTarget

        context = NavigationContext(
            self.app, owner or self.selected_tab, self.app.project_dir, actor
        )
        identity = await DirectTarget(thread).open(context)
        await self.step()
        return identity

    async def return_to_owner(self) -> None:
        await ReturnToViewAction().apply(self.app.selected_session)
        await self.step()

    async def go_back(self) -> None:
        self.app.tab_order.navigate(-1)
        await self.step()

    async def go_forward(self) -> None:
        self.app.tab_order.navigate(+1)
        await self.step()

    def can_go_back(self) -> bool:
        return not self.app.screen.query_one(BackTabButton).disabled

    def can_go_forward(self) -> bool:
        return not self.app.screen.query_one(ForwardTabButton).disabled

    async def open_preview(self, path) -> str:
        identity = await self.app.session_navigation.preview(path)
        await self.step()
        return identity

    async def thread_renamed(self, owner: str, previous: str, current: str) -> None:
        self.app.session_navigation.sync_identity(owner, previous, current)
        await self.step()

    async def step(self, seconds: float | None = None) -> None:
        await self.pilot.pause(seconds)

    async def revealed(self, sidebar):
        """Show a sidebar and return it once its panels are mounted."""
        sidebar.reveal()
        await self.panels_loaded(sidebar)
        return sidebar

    async def panels_loaded(self, sidebar) -> None:
        """Wait until a sidebar's panels are mounted."""
        await self.until(lambda: sidebar.panels_loaded, seconds=12, why="the sidebar's panels")

    @property
    def core_service(self):
        return self.app.coordination_access.observation.observed().service

    def failure(self) -> BaseException | None:
        return self.app._exception or self.errors.unexpected(self)

    @contextmanager
    def reporting_error(self) -> Iterator[None]:
        """The enclosed steps show exactly one error on purpose; it is acknowledged when they end,
        and any second error saved in the same steps fails the test instead of hiding behind it."""
        if unexpected := self.errors.unexpected(self):
            raise unexpected
        before = frozenset(self.reported_errors())
        self.errors = ExpectsErrors()
        try:
            yield
        finally:
            saved = frozenset(self.reported_errors())
            self.errors = RefusesErrors(saved)
        new = sorted(saved - before)
        if len(new) != 1:
            raise ReportedError(f"expected exactly one reported error, the app saved {len(new)}: "
                                + "".join(f"\n{path.name}:\n{path.read_text()}" for path in new))

    def reported_errors(self) -> list[Path]:
        return sorted(paths.get_errors().glob("*.txt"))
