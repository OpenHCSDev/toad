"""The flash: a transient one-row notice shown briefly when an action completes, succeeds
or errors. Its tones (`FlashTone`), the notice that shows one (`FlashNotice`: Textual's
`widgets.flash.Flash`, Qt's `QtFlash`) and the view that flashes through its notice
(`FlashHost`), so callers flash without knowing the backend.

Loads no toolkit: every shared conversation contract is a `FlashHost`, and the tones and the
notice sat in `client.prompt_stack`, whose key modes load Textual.

`FlashHost` is a plain class (not ABC) so toolkit metaclasses can co-exist in the MRO.
"""
from __future__ import annotations

from abc import abstractmethod
from typing import ClassVar

from agent_comms.nominal.declared_family import DeclaredFamily
from metaclass_registry import AbstractHooksMeta
from ui_theme.scheme import ErrorColour, PrimaryColour, SuccessColour, ThemeColour, WarningColour


class FlashTone(DeclaredFamily, affix="Tone"):
    """A flash's semantic kind and the theme colour it is tinted with; callers name it."""

    colour: ClassVar[type[ThemeColour]]


class DefaultTone(FlashTone):
    colour = PrimaryColour


class SuccessTone(FlashTone):
    colour = SuccessColour


class WarningTone(FlashTone):
    colour = WarningColour


class ErrorTone(FlashTone):
    colour = ErrorColour


class FlashNotice(metaclass=AbstractHooksMeta):
    """The transient one-row notice under the transcript.

    `flash` is the one procedure: stop the running hide, show the content in its tone,
    and hide it again after `duration` seconds, or the `ui.flash_duration` setting."""

    @property
    def settings(self):
        """The settings whose `ui.flash_duration` bounds a flash with no duration."""
        return self.app.settings

    def flash(self, content, *, duration: float | None = None, style: str = DefaultTone.declared_name) -> None:
        self.stop_flash_timer()
        self.show_flash(content, FlashTone.member_named(style))
        if duration is None:
            duration = self.settings.ui.flash_duration
        self.start_flash_timer(duration or 3)

    @abstractmethod
    def show_flash(self, content, tone: type[FlashTone]) -> None:
        """Paint the content in the tone and show the row."""

    @abstractmethod
    def hide_flash(self) -> None:
        """Hide the row without reserving its space."""

    @abstractmethod
    def stop_flash_timer(self) -> None:
        """Cancel the pending hide of an earlier flash."""

    @abstractmethod
    def start_flash_timer(self, seconds: float) -> None:
        """Call `hide_flash` after `seconds`."""


class FlashHost:
    """A view that can flash a transient status message. Its `feedback`, a `FlashNotice`,
    owns how the text is drawn and how long it stays; callers only supply the text.

    Each frontend's conversation wrote these three itself, the same call with its own name
    for the tone (2026-11-22: NRA's sibling-override-step finding)."""

    def flash(self, text: str) -> None:
        """Flash a neutral status message."""
        self.feedback.flash(self.flash_content(text))

    def flash_success(self, text: str) -> None:
        """Flash a success-styled status message."""
        self.feedback.flash(self.flash_content(text), style=SuccessTone.declared_name)

    def flash_error(self, text: str) -> None:
        """Flash an error-styled status message."""
        self.feedback.flash(self.flash_content(text), style=ErrorTone.declared_name)

    def flash_content(self, text: str):
        """`text` as the notice draws it: itself, unless the toolkit would read markup in it."""
        return text
