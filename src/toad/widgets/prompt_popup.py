"""The mounted prompt widgets own their opening, focus and dismissal."""
from __future__ import annotations

import asyncio
from abc import abstractmethod
from typing import TYPE_CHECKING, ClassVar, Self

from textual import events, on
from textual.app import ComposeResult
from textual.containers import VerticalGroup
from textual.reactive import var

from toad.declared_widget import DeclaredWidget
from toad.messages import Dismiss
from toad.widget_actions import DismissibleControl

if TYPE_CHECKING:
    from toad.prompt_cursor import CursorMovement
    from toad.widgets.prompt import Prompt


class PromptPopup(DismissibleControl, DeclaredWidget, VerticalGroup):
    """One mounted popup is the authority for its open state and interaction."""

    requires_completion: ClassVar[bool] = False

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

    def check_consume_key(self, key: str, character: str | None = None) -> bool:
        # The popup's actual declarations outrank ancestor shortcuts, even
        # before a priority Key event reaches its focused control.
        if not self.is_open:
            return super().check_consume_key(key, character)
        bindings = self.binding_map(self.screen.active_binding_mode)
        bindings.apply_keymap(self.app._keymap)
        return key in bindings.key_to_bindings or super().check_consume_key(key, character)

    def can_open(self) -> bool:
        return not self.requires_completion or self.prompt.supports_completion

    def compose(self) -> ComposeResult:
        if self._content_build is not None:
            yield from self.compose_content()

    @abstractmethod
    def compose_content(self) -> ComposeResult:
        """The popup's controls, composed when it is first used."""

    def focus(self, scroll_visible: bool = False) -> Self:
        build = self._content_build
        if build is None:
            if not self.can_open():
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
        if not self.can_open():
            return False
        for popup in self.prompt.query(PromptPopup):
            if popup is not self:
                popup.is_open = False
        self.prompt.prompt_text_area.suggestion = ""
        self.is_open = True
        return True

    def dismiss_control(self) -> None:
        if self.is_open:
            self.is_open = False
            self.prompt.prompt_text_area.suggestion = ""
            self.prompt.focus()

    @on(Dismiss)
    def dismiss_popup(self, event: Dismiss) -> None:
        if event.widget is self:
            event.stop()
            self.dismiss_control()

    def on_descendant_blur(self, event: events.DescendantBlur) -> None:
        # A move between the popup's children is not a departure from the popup.
        self.call_later(self.close_if_unfocused)

    def close_if_unfocused(self) -> None:
        if not self.has_focus_within:
            self.is_open = False


class CompletionPopup(PromptPopup):
    """Completion widgets appear above the editor; membership is derived."""

    @classmethod
    def cursor_changed_in(cls, prompt: Prompt, movement: CursorMovement) -> None:
        for popup in prompt.query(cls):
            popup.cursor_changed(movement)

    def cursor_changed(self, movement: CursorMovement) -> None:
        """Cases without cursor-triggered entry retain their existing control."""


class InfoPopup(PromptPopup):
    """Session choices appear alongside the prompt's session information."""
