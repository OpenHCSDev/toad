"""The prompt's decisions without a toolkit: Textual's `Prompt` and Qt's `Composer` inherit them.

What a composer submits to, whether its queue holds Enter, what its queue summary says,
which glyph leads the input, how a returned draft joins what was typed since, and the
status the info bar shows all live here. The frontends keep their own editor, focus and
paint calls.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import ClassVar

from agent_comms.messaging.message_files import FileUpload
from metaclass_registry import AbstractHooksMeta
from ui_theme.scheme import InputToneColour, PromptToneColour, ThemeColour, TurnBandColour

from toad.client.input_decision import InputDecision
from toad.setting_declarations import EachOpenWidget


class PromptSettingEffects:
    """A prompt follows the input box settings: these are their effects on every open
    prompt, Textual's `Prompt` and Qt's `Composer` alike. Each reads through the prompt's
    own settings scope, so a view's override reaches only that view's prompt."""

    @EachOpenWidget
    def apply_input_layout(self) -> None:
        """The input box setting changed: the prompt takes the room it now names."""
        self.place_input_box()

    @EachOpenWidget
    def apply_input_text(self) -> None:
        """The placeholder or a leading symbol changed: the prompt shows the new text."""
        self.update_prompt()

    @EachOpenWidget
    def apply_delivery_preview(self) -> None:
        """The delivery preview was turned on or off: the prompt reads it again and shows its
        queue rows, or drops them for the held count, at once."""
        self.kept_delivery_preview = None
        self.sync_queue()


class PromptComposer(metaclass=AbstractHooksMeta):
    """A conversation's composer: its submission owner, queue and leading glyph."""

    submissions: object | None
    kept_delivery_preview: bool | None = None
    """The delivery-preview setting as this prompt last read it, until it changes
    (`PromptSettingEffects.apply_delivery_preview`): a queue sync reads it several times, and
    each read resolved it through the settings scope again (~8% of the phone's main thread
    during a burst of arrivals, 2026-11-18)."""
    queue_summary_lines: ClassVar[int] = 3
    """The queue summary's most lines; a longer one is cut there, so its wrapping never
    pushes the history further."""
    maximum_editor_viewport_percent: ClassVar[int] = 50
    """The visible viewport the editor may occupy before its own scrolling takes over.

    Textual expresses this as ``vh`` and Qt resolves it to native pixels after Android's
    keyboard resizes the window.  It is one layout fact, not a terminal percentage beside
    a phone-only line count.
    """
    # The surface the composer's area is painted on, a tier off the transcript above it.
    area_tone: ClassVar[type[ThemeColour]] = PromptToneColour
    # The delivery and queue lines' band over that area, and the field typed into, a tier off
    # both: each interactive part of the composer is its own surface, in both frontends.
    queue_tone: ClassVar[type[ThemeColour]] = TurnBandColour
    input_tone: ClassVar[type[ThemeColour]] = InputToneColour

    @property
    @abstractmethod
    def settings(self):
        """The settings whose `ui.input` symbols lead the input."""

    @classmethod
    def visible_editor_lines(
        cls, typed_lines: int, viewport_height: int, line_height: int, vertical_room: int = 0
    ) -> int:
        """Lines shown before the editor scrolls, under the shared viewport limit.

        ``vertical_room`` is native room inside the editor that is not a text line (Qt's
        document margins).  Borders and the rest of the composer remain outside this editor
        limit in both frontends.
        """
        available = viewport_height * cls.maximum_editor_viewport_percent // 100 - vertical_room
        limit = max(1, available // max(1, line_height))
        return min(max(1, typed_lines), limit)

    @property
    def operational_submissions(self):
        if self.submissions is None:
            raise RuntimeError("Operational prompt requires its submission owner")
        return self.submissions

    @property
    def conversation(self):
        """The view this composer submits to; its submission owner holds it, so the
        composer answers the same whether it is mounted inside that view or beside it."""
        return self.operational_submissions.view

    @property
    def input_decision(self) -> InputDecision:
        return self.operational_submissions.input_decision

    @property
    def agent_ready(self) -> bool:
        return self.input_decision.allows

    @property
    def holds_input(self) -> bool:
        """Whether this composer's queue takes Enter or waits to be sent; its source answers."""
        return self.operational_submissions.holds_input

    @property
    def offers_send_now(self) -> bool:
        """Send now (Ctrl+Enter) sends ahead while input is held for a ready agent."""
        return self.agent_ready and self.holds_input

    @property
    def shows_delivery_preview(self) -> bool:
        """The `ui.input.delivery_preview` setting: the queue rows above the prompt, or only
        the held count in the info bar."""
        if self.kept_delivery_preview is None:
            self.kept_delivery_preview = bool(self.settings.ui.input.delivery_preview)
        return self.kept_delivery_preview

    @property
    def shows_delivery_controls(self) -> bool:
        """The delivery controls row ("Enter queues · Send now") shows while Send now is
        offered and the preview is on; with it off, Ctrl+Enter still sends ahead."""
        return self.shows_delivery_preview and self.offers_send_now

    @property
    def queue_summary(self) -> str:
        """The queue rows' text; while the preview is off nothing is read for them."""
        return self.operational_submissions.queue_summary if self.shows_delivery_preview else ""

    @property
    def queue_hint(self) -> str:
        """The info bar's held count while the preview is off; nothing while it is on."""
        return "" if self.shows_delivery_preview else self.operational_submissions.queue_hint

    @abstractmethod
    def sync_queue(self) -> None:
        """Show the queue rows, the delivery controls and the held count as the shared answers say."""

    def prompt_symbol(self, text: str, shell_mode: bool) -> str:
        """The glyph that leads the input: shell, multiline or the agent prompt (``❯``)."""
        symbols = self.settings.ui.input
        if shell_mode:
            return symbols.shell_symbol
        return symbols.multiline_symbol if "\n" in text or "```" in text else symbols.agent_symbol

    def offer_files(self, takes_files: bool) -> None:
        """Whether this composer's bus takes files. A prompt to an agent attaches none, so it
        offers none either way; a message composer offers Attach while its bus takes them."""

    @abstractmethod
    def show_failure(self, text: str) -> None:
        """Say, under the input, why something typed or attached did not go."""

    def restore_draft(self, text: str) -> None:
        """Join returned text to what is typed (`restored_suffix`)."""
        if suffix := self.restored_suffix(self.text, text):
            self.append_to_draft(suffix)

    @abstractmethod
    def append_to_draft(self, suffix: str) -> None:
        """Put `suffix` at the end of what is typed, as an edit the reader can undo."""

    def restore(self, draft) -> None:
        """A send that did not land comes back as the draft."""
        self.restore_draft(draft.source_text)

    def take_files(self) -> tuple[FileUpload, ...]:
        """The files the input being sent carries: an agent prompt attaches none."""
        return ()

    @staticmethod
    def restored_suffix(current: str, text: str) -> str:
        """What a send that did not land appends to the draft: nothing when the draft
        already holds it, else the text after a blank line."""
        if not text or current == text or current.endswith("\n\n" + text):
            return ""
        return ("\n\n" if current else "") + text


class ComposerStatus:
    """The status the info bar shows: why compose is held, else the thread's own status
    from its owner (Core's configuration answer for a CLI thread, the context measurement
    for a native agent)."""

    thread_status: object = ""
    composer_block: str = ""

    def composed_status(self):
        return self.composer_block or self.thread_status
