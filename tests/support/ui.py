"""The questions a test asks the running interface, whichever toolkit draws it.

A test that needs only these questions says nothing about Textual and keeps its
meaning when another frontend answers them. A test of paint, layout or widget
internals asks for ``ui.textual`` instead and lives under ``tests/textual``.
"""

from __future__ import annotations

import asyncio
import inspect
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from support.agents import AppAgents
from toad.navigation_context import NavigationContext

if TYPE_CHECKING:
    from textual.pilot import Pilot

    from toad.app import ToadApp


class NotShown(AssertionError):
    """The screen never showed what the test waited for; carries the last screen."""


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
    async def press(self, *keys: str) -> None: ...

    @abstractmethod
    async def click(self, text: str, *, occurrence: int = 0) -> None:
        """Click the first cell of `text` where it is drawn on screen."""

    @abstractmethod
    def link_at(self, text: str, *, occurrence: int = 0) -> tuple[str, tuple] | None:
        """The action a click on `text` would trigger, as (name, arguments), if it is a link."""

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
    def sender_of(self, identity: str) -> str:
        """The thread name a channel or direct-message tab sends as."""

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
                    result = condition()
                    if inspect.isawaitable(result):
                        result = await result
                    if result:
                        return
                    await self.step(0.02)
        except TimeoutError:
            raise NotShown(
                f"{why or 'condition'} not reached in {seconds}s; screen:\n{self.visible_text()}"
            ) from None

    async def until_agent_ready(self, *, seconds: float = 30) -> None:
        await self.until(
            self.agent_ready, seconds=seconds, why="the agent to accept input"
        )

    async def until_shows(self, text: str, *, seconds: float = 10) -> None:
        await self.until(
            lambda: self.shows(text), seconds=seconds, why=f"{text!r} on screen"
        )


class TextualUi(AppAgents, Ui):
    """Toad drawn by Textual, driven headless through Textual's pilot; its agents attach to that app."""

    def __init__(self, app: ToadApp, pilot: Pilot) -> None:
        super().__init__(app)
        self.pilot = pilot

    @property
    def textual(self) -> tuple[ToadApp, Pilot]:
        """The Textual app and pilot, for tests of Textual-owned behaviour only."""
        return self.app, self.pilot

    def visible_lines(self) -> list[str]:
        return [strip.text for strip in self.app.screen._compositor.render_strips()]

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

    async def press(self, *keys: str) -> None:
        await self.pilot.press(*keys)
        await self.step()

    def _cell_of(self, text: str, occurrence: int) -> tuple[int, int]:
        """The screen cell where the nth drawn `text` starts."""
        from rich.cells import cell_len

        places = [
            (cell_len(line[: line.find(text)]), y)
            for y, line in enumerate(self.visible_lines())
            if text in line
        ]
        if len(places) <= occurrence:
            raise NotShown(f"{text!r} is not on screen:\n{self.visible_text()}")
        return places[occurrence]

    async def click(self, text: str, *, occurrence: int = 0) -> None:
        assert await self.pilot.click(
            offset=self._cell_of(text, occurrence)
        ), f"the click on {text!r} left the screen"
        await self.step()

    def link_at(self, text: str, *, occurrence: int = 0) -> tuple[str, tuple] | None:
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
            lambda: MainScreen(app.project_dir, app.agent_binding)
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
        await self.app.selected_session.action_back_to_agent()
        await self.step()

    async def go_back(self) -> None:
        self.app.tab_order.navigate(-1)
        await self.step()

    async def go_forward(self) -> None:
        self.app.tab_order.navigate(+1)
        await self.step()

    def can_go_back(self) -> bool:
        return not self.app.screen.query_one("#tab-back").has_class("-unavailable")

    def can_go_forward(self) -> bool:
        return not self.app.screen.query_one("#tab-forward").has_class("-unavailable")

    async def open_preview(self, path) -> str:
        identity = await self.app.session_navigation.preview(path)
        await self.step()
        return identity

    def sender_of(self, identity: str) -> str:
        return self.app.workspace_sessions.require(identity).me

    async def thread_renamed(self, owner: str, previous: str, current: str) -> None:
        self.app.session_navigation.sync_identity(owner, previous, current)
        await self.step()

    async def step(self, seconds: float | None = None) -> None:
        await self.pilot.pause(seconds)

    @property
    def core_service(self):
        return self.app.coordination_access.service

    def failure(self) -> BaseException | None:
        return self.app._exception
