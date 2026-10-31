"""Input permission and its explanation are the same decision."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from agent_comms.nominal.declared_family import DeclaredFamily
from textual.content import Content

from toad import messages

if TYPE_CHECKING:
    from toad.acp.agent_session import SessionDisposition
    from toad.widgets.prompt import PromptTextArea


class InputDecision(DeclaredFamily, ABC):
    allows: ClassVar[bool]

    @abstractmethod
    def then(self, next: Callable[[], InputDecision]) -> InputDecision: ...

    @abstractmethod
    def agent_info_text(self, agent_info: Content) -> Content: ...

    @abstractmethod
    def announce(self, editor: PromptTextArea) -> None: ...


class InputAccepted(InputDecision):
    allows = True

    def then(self, next: Callable[[], InputDecision]) -> InputDecision:
        return next()

    def agent_info_text(self, agent_info: Content) -> Content:
        return agent_info

    def announce(self, editor: PromptTextArea) -> None:
        """Accepted input needs no refusal feedback."""


class InputRefused(InputDecision):
    allows = False

    @property
    @abstractmethod
    def message(self) -> str: ...

    def then(self, next: Callable[[], InputDecision]) -> InputDecision:
        return self

    def agent_info_text(self, agent_info: Content) -> Content:
        return Content(self.message)

    def announce(self, editor: PromptTextArea) -> None:
        editor.app.bell()
        editor.post_message(messages.Flash(self.message, "error"))


@dataclass(frozen=True)
class NoLiveAgent(InputRefused):
    disposition: SessionDisposition

    @property
    def message(self) -> str:
        return self.disposition.refusal_notice


class ModelSelectionRequired(InputRefused):
    message = "Choose a model or connect a provider (click here). Your draft is kept."


class OwnerNotAttached(InputRefused):
    message = "No live owner binding for this thread; its input stays read-only. Your draft is kept."
