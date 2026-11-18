"""The prompt's decisions without a toolkit: Textual's `Prompt` and Qt's `Composer` inherit them.

What a composer submits to, whether its queue holds Enter, what its queue summary says,
which glyph leads the input, how a returned draft joins what was typed since, and the
status the info bar shows all live here. The frontends keep their own editor, focus and
paint calls.
"""

from __future__ import annotations

from abc import abstractmethod

from metaclass_registry import AbstractHooksMeta

from toad.client.input_decision import InputAccepted, InputDecision
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


class PromptComposer(metaclass=AbstractHooksMeta):
    """A conversation's composer: its submission owner, queue and leading glyph."""

    submissions: object | None

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
        """Delivery controls ("Enter queues · Send now") show while input is held for a
        ready agent."""
        return self.agent_ready and self.holds_input

    @property
    def queue_summary(self) -> str:
        return self.operational_submissions.queue_summary

    def prompt_symbol(self, text: str, shell_mode: bool) -> str:
        """The glyph that leads the input: shell, multiline or the agent prompt (``❯``)."""
        symbols = self.settings.ui.input
        if shell_mode:
            return symbols.shell_symbol
        return symbols.multiline_symbol if "\n" in text or "```" in text else symbols.agent_symbol

    @staticmethod
    def restored_suffix(current: str, text: str) -> str:
        """What a send that did not land appends to the draft: nothing when the draft
        already holds it, else the text after a blank line."""
        if not text or current == text or current.endswith("\n\n" + text):
            return ""
        return ("\n\n" if current else "") + text


class MessagePromptComposer(PromptComposer):
    """A message composer: always the agent glyph, and every input is accepted."""

    @property
    def input_decision(self) -> InputDecision:
        """A message is accepted whether or not an agent is attached: its submission owner
        refuses a send it cannot make. An agent prompt asks its owner instead."""
        return InputAccepted()

    def prompt_symbol(self, text: str, shell_mode: bool) -> str:
        return self.settings.ui.input.agent_symbol


class ComposerStatus:
    """The status the info bar shows: why compose is held, else the thread's own status
    from its owner (Core's configuration answer for a CLI thread, the context measurement
    for a native agent)."""

    thread_status: object = ""
    composer_block: str = ""

    def composed_status(self):
        return self.composer_block or self.thread_status
