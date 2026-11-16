"""Input permission and its explanation are the same decision."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import ClassVar

from agent_comms.nominal.declared_family import DeclaredFamily

from toad.acp.agent_session import SessionDisposition


class InputDecision(DeclaredFamily, ABC):
    """Whether the user's input is accepted or refused, and why.

    Native presentation (Content rendering, bell/flash feedback) stays
    on native members. The shared contract owns allows, chaining and
    the refusal message text.
    """

    allows: ClassVar[bool]

    @abstractmethod
    def then(self, next: Callable[[], InputDecision]) -> InputDecision: ...

    @abstractmethod
    def explanation(self) -> str:
        """Plain text explaining this decision for the agent info line."""

    @abstractmethod
    def announce_to(self, editor: object) -> None:
        """Notify the native editor of this decision. The editor type
        is the native widget; the shared contract does not import it."""


class InputAccepted(InputDecision):
    allows = True

    def then(self, next: Callable[[], InputDecision]) -> InputDecision:
        return next()

    def explanation(self) -> str:
        return ""

    def announce_to(self, editor: object) -> None:
        pass


class InputRefused(InputDecision):
    allows = False

    @property
    @abstractmethod
    def message(self) -> str: ...

    def then(self, next: Callable[[], InputDecision]) -> InputDecision:
        return self

    def explanation(self) -> str:
        return self.message

    def announce_to(self, editor: object) -> None:
        pass


@dataclass(frozen=True)
class NoLiveAgent(InputRefused):
    disposition: SessionDisposition

    @property
    def message(self) -> str:
        return self.disposition.refusal_notice


class TranscriptNotReady(InputRefused):
    message = "This conversation's transcript is not ready yet. Your draft is kept."


class ModelSelectionRequired(InputRefused):
    message = "Choose a model or connect a provider (click here). Your draft is kept."


class OwnerNotAttached(InputRefused):
    message = "No live owner binding for this thread; its input stays read-only. Your draft is kept."
