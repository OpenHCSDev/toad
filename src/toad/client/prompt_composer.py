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
        """The delivery preview was turned on or off: the prompt shows its queue rows, or
        drops them for the held count, at once."""
        self.sync_queue()


class PromptComposer(metaclass=AbstractHooksMeta):
    """A conversation's composer: its submission owner, queue and leading glyph."""

    submissions: object | None
    queue_summary_lines: ClassVar[int] = 3
    """The queue summary's most lines; a longer one is cut there, so its wrapping never
    pushes the history further."""

    @property
    @abstractmethod
    def settings(self):
        """The settings whose `ui.input` symbols lead the input."""

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
        return self.settings.ui.input.delivery_preview

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

    @abstractmethod
    def show_failure(self, text: str) -> None:
        """Say, under the input, why something typed or attached did not go."""

    @abstractmethod
    def restore_draft(self, text: str) -> None:
        """Join returned text to what is typed (`restored_suffix`)."""

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
