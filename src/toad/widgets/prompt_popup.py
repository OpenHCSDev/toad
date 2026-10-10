"""The mounted prompt widgets own their opening, focus and dismissal."""
from __future__ import annotations

import asyncio
from abc import abstractmethod
from typing import TYPE_CHECKING, Self

from agent_comms.declared_family import DeclaredFamily
from textual import events, on
from textual.app import ComposeResult
from textual.containers import VerticalGroup
from textual.reactive import var

from toad.messages import Dismiss

if TYPE_CHECKING:
    from toad.widgets.prompt import Prompt


class _PopupMeta(type(DeclaredFamily), type(VerticalGroup)):
    """Compose the existing family and Textual message-pump metaclasses."""


class PromptPopup(DeclaredFamily, VerticalGroup, metaclass=_PopupMeta, affix="Popup"):
    """One mounted popup is the authority for its open state and interaction."""

    DEFAULT_CSS = "PromptPopup { display: none; } PromptPopup.-open { display: block; }"
    is_open = var(False, toggle_class="-open")
    # Content is built on first use: an unused popup is one widget, not its
    # whole tree, in every conversation's build and layout. The build's own
    # future is its state: absent, running, or done.
    _content_build: asyncio.Future | None = None

    @classmethod
    @abstractmethod
    def for_prompt(cls, prompt: Prompt) -> Self | None:
        """Construct and bind this case, or decline this kind of composer."""

    @property
    def prompt(self) -> Prompt:
        from toad.widgets.prompt import Prompt
        return self.query_ancestor(Prompt)

    def admitted(self) -> bool:
        return True

    def compose(self) -> ComposeResult:
        if self._content_build is not None:
            yield from self.compose_content()

    @abstractmethod
    def compose_content(self) -> ComposeResult:
        """The popup's controls, composed when it is first used."""

    def focus(self, scroll_visible: bool = False) -> Self:
        build = self._content_build
        if build is None:
            if not self.admitted():
                return self
            # Built while still hidden, so the popup opens with its content.
            # The state exists before the build runs: compose reads it, and an
            # eager task would otherwise compose before the assignment.
            build = self._content_build = asyncio.get_running_loop().create_future()
            self.call_next(self._build_content, build)
        if build.done():
            build.result()
            if self.open():
                self.focus_content(scroll_visible)
        else:
            self.call_next(self._focus_when_built, build, scroll_visible)
        return self

    async def _build_content(self, build: asyncio.Future) -> None:
        try:
            await self.recompose()
        except BaseException as error:
            build.set_exception(error)
            raise
        build.set_result(None)

    async def _focus_when_built(self, build: asyncio.Future, scroll_visible: bool) -> None:
        await build
        if self.open():
            self.focus_content(scroll_visible)

    @abstractmethod
    def focus_content(self, scroll_visible: bool) -> None:
        """The leaf focuses its own control; opening and eligibility are shared."""

    def open(self) -> bool:
        if not self.admitted():
            return False
        for popup in self.prompt.query(PromptPopup):
            if popup is not self:
                popup.is_open = False
        self.prompt.prompt_text_area.suggestion = ""
        self.is_open = True
        return True

    def action_dismiss(self) -> None:
        if self.is_open:
            self.is_open = False
            self.prompt.prompt_text_area.suggestion = ""
            self.prompt.focus()

    @on(Dismiss)
    def dismiss_popup(self, event: Dismiss) -> None:
        if event.widget is self:
            event.stop()
            self.action_dismiss()

    def on_descendant_blur(self, event: events.DescendantBlur) -> None:
        # A move between the popup's children is not a departure from the popup.
        self.call_later(self.close_if_unfocused)

    def close_if_unfocused(self) -> None:
        if not self.has_focus_within:
            self.is_open = False


class CompletionPopup(PromptPopup):
    """Completion widgets appear above the editor; membership is derived."""

    def cursor_changed(self, movement) -> None:
        """Cases without cursor-triggered entry retain their existing control."""


class InfoPopup(PromptPopup):
    """Session choices appear alongside the prompt's session information."""
