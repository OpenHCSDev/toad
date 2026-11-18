"""The rows under a conversation's transcript, without a toolkit.

Textual's `Conversation.compose` draws, under the transcript: the flash notice, the
`PromptStack` (activity sweep, the session-status disclosure, the goal bar, the prompt)
and, inside the prompt, its info bar (editing mode, status line). Each row's decision
lives here; Textual's widgets and the Qt widgets inherit the same parent and only paint.

- `FlashNotice` — the transient centred notice ("Agent Comms connected"), its tone and
  how long it stays.
- `ObservedSweep` — the activity sweep, painted from its owner's `working()` answer.
- `SessionStatusTitle` — the collapsed session-status line: its role by status type and
  its text from the status row, saved history and delivery.
- `SettingVisible` — a row a UI setting shows or hides (`ui.info_bar`, `ui.status_line`).
- `EditingModeBadge` — the info bar's editing-mode badge (``STANDARD`` while unfocused).
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Callable, Iterable
from typing import ClassVar

from agent_comms.nominal.declared_family import DeclaredFamily
from agent_comms.registry.thread_presentation import (
    SessionDisconnected,
    ThreadPresentationStatus,
    ThreadRetired,
    WorkingThreadPresentationStatus,
)
from agent_comms.ui_model.delivery import DeliveryView
from agent_comms.ui_model.status import ThreadStatusModel
from metaclass_registry import AbstractHooksMeta
from metaclass_registry.mro_dispatch import handles
from ui_theme.effects import ACTIVITY_SWEEP, Ribbon
from ui_theme.scheme import ErrorColour, PrimaryColour, SuccessColour, ThemeColour, WarningColour

from toad.client.line_blocks import LineRole, MutedRole, NoticeRole, WorkingRole
from toad.core.projection import MroProjection
from toad.key_modes import Standard


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
    @abstractmethod
    def settings(self):
        """The settings whose `ui.flash_duration` bounds a flash with no duration."""

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


class ObservedSweep:
    """The activity sweep drawn from an existing activity owner, never a busy mirror.

    The owner's answer is `Conversation.working()` / `WorkingStatusOwner.working()`: the
    turn is busy, the observed thread is working, or saved history is loading. The ribbon
    and its cadence are the shared `ACTIVITY_SWEEP`."""

    effect: ClassVar[Ribbon] = ACTIVITY_SWEEP

    def __init__(self, read_busy: Callable[[], bool], **kwargs) -> None:
        self._read_busy = read_busy
        super().__init__(**kwargs)

    def read_busy(self) -> bool:
        return self._read_busy()


class SessionStatusTitle(MroProjection[type[LineRole]]):
    """The collapsed session-status line: what the observed thread is doing, with saved
    history and delivery joined after it, inked by the status's type."""

    @handles(ThreadPresentationStatus)
    def idle_role(self, status) -> type[LineRole]:
        return NoticeRole if status.details else MutedRole

    @handles(WorkingThreadPresentationStatus)
    def working_role(self, status) -> type[LineRole]:
        return WorkingRole

    @handles(ThreadRetired)
    def retired_role(self, status) -> type[LineRole]:
        return NoticeRole

    @handles(SessionDisconnected)
    def disconnected_role(self, status) -> type[LineRole]:
        return NoticeRole

    def title_role_for(self, row: ThreadStatusModel, cursor) -> type[LineRole]:
        """The title's ink: the row's status as the saved-history cursor presents it."""
        return self.project_value(cursor.present_status(row.status))

    @property
    def title_names(self) -> tuple[str, ...]:
        """The operational row is its own session; its status leads the title."""
        return ()

    def summary_title(self, row: ThreadStatusModel, history: Iterable[str], delivery: DeliveryView) -> str:
        """The collapsed row: its status, saved history and what delivery has to say.

        Delivery's parts come from delivery, which is the point: this line used to spell
        the notice count itself while the bar inside the expanded contents spelled the same
        count its own way. One owner now, joined by whoever is joining."""
        return " · ".join((
            *self.title_names, *row.summary, *history,
            *delivery.parts(),
            *(("Delivery unavailable",) if delivery.error else ()),
        ))

    @staticmethod
    def detail_text(row: ThreadStatusModel) -> str:
        """The status is already the disclosure's title, not a second row inside."""
        return "\n".join(row.lines[1:])

    @staticmethod
    def shown(row: ThreadStatusModel) -> bool:
        return bool(row.summary and row.summary[0])


class SettingVisible:
    """A row one boolean UI setting shows or hides."""

    visibility_setting: ClassVar[str]

    def __init_subclass__(cls, *, setting: str | None = None, **kwargs):
        super().__init_subclass__(**kwargs)
        if setting is not None:
            cls.visibility_setting = setting

    def setting_visible(self, configuration_state) -> bool:
        return bool(configuration_state.get_resolved_value(self.visibility_setting))


class EditingModeBadge(metaclass=AbstractHooksMeta):
    """The info bar's editing-mode badge: the editor's mode while it has focus, else the
    standard mode, as the TUI shows ``STANDARD`` under an unfocused prompt."""

    def present_editing_mode(self, mode, focused: bool) -> None:
        self.show_mode_label((mode if focused else Standard()).label)

    @abstractmethod
    def show_mode_label(self, label: str) -> None:
        """Paint the badge text."""
