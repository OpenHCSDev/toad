"""Input permission and its explanation are the same decision."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import ClassVar

from agent_comms.nominal.declared_family import DeclaredFamily

from toad.acp.agent_session import SessionDisposition


class RefusalFeedback:
    """A native editor tells the user their input was refused."""

    def refuse_input(self, message: str) -> None:
        raise NotImplementedError


class InputDecision(DeclaredFamily, ABC):
    """Whether the user's input is accepted or refused, and why.

    The native editor supplies how a refusal is shown (RefusalFeedback) and
    how the agent line is rendered (the refusal callable).
    """

    allows: ClassVar[bool]

    @abstractmethod
    def then(self, next: Callable[[], InputDecision]) -> InputDecision: ...

    @abstractmethod
    def agent_info[T](self, agent_info: T, refusal: Callable[[str], T]) -> T: ...

    @abstractmethod
    def announce(self, editor: RefusalFeedback) -> None: ...


class InputAccepted(InputDecision):
    allows = True

    def then(self, next: Callable[[], InputDecision]) -> InputDecision:
        return next()

    def agent_info[T](self, agent_info: T, refusal: Callable[[str], T]) -> T:
        return agent_info

    def announce(self, editor: RefusalFeedback) -> None:
        """Accepted input needs no refusal feedback."""


class InputRefused(InputDecision):
    allows = False

    @property
    @abstractmethod
    def message(self) -> str: ...

    def then(self, next: Callable[[], InputDecision]) -> InputDecision:
        return self

    def agent_info[T](self, agent_info: T, refusal: Callable[[str], T]) -> T:
        return refusal(self.message)

    def announce(self, editor: RefusalFeedback) -> None:
        editor.refuse_input(self.message)


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
