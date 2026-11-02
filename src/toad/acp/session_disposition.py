"""Session state and its presentation, independent of handshake execution."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import ClassVar

from agent_comms.nominal.declared_family import DeclaredFamily
from agent_comms.owner_protocol import IncompatibleOwner
from agent_comms.thread_presentation import SessionDisconnected

from toad.core.events import AgentFail
from toad.failure_presentation import FailurePresentation
from toad.live_output import LiveOutput


class SessionLoginTarget(ABC):
    """The rich output that an ordinary login may clear."""

    output: LiveOutput

    @abstractmethod
    async def prune_window(self, low_mark: int, high_mark: int) -> None: ...


class SessionCloseTarget(ABC):
    @abstractmethod
    def connection_closed(self) -> None: ...


class SessionDisposition(DeclaredFamily, affix="SessionDisposition"):
    accepts_updates = False
    # Whether leaving a shared process must ask it to close this session.
    held_by_agent = True
    unready_line: ClassVar[str] = "No agent is connected to this tab. Your draft is kept."

    def close(self, target: SessionCloseTarget) -> SessionDisposition:
        return self

    def present[T](self, ordinary: T, show: Callable[[SessionDisconnected], T]) -> T:
        """One session presentation, projected into a row or an input notice."""
        return ordinary

    @property
    def refusal_notice(self) -> str:
        """Explain this session's refusal without borrowing thread activity."""
        return self.present(self.unready_line, lambda status: status.notice)

    async def present_failure(self, failure: AgentFail, view: FailurePresentation) -> None:
        await failure.present(view)


class SessionLifetime(ABC):
    """The identity and state retained by a session's captured authority."""

    @property
    @abstractmethod
    def disposition(self) -> SessionDisposition: ...

    @property
    def accepts_updates(self) -> bool:
        return self.disposition.accepts_updates


class UnopenedSessionDisposition(SessionDisposition):
    held_by_agent = False


class UnavailableSessionDisposition(SessionDisposition):
    @property
    @abstractmethod
    def status(self) -> SessionDisconnected: ...

    def present[T](self, ordinary: T, show: Callable[[SessionDisconnected], T]) -> T:
        return show(self.status)


@dataclass(frozen=True)
class ActiveSessionDisposition(SessionDisposition):
    session: SessionLifetime
    accepts_updates = True
    unready_line = "Connecting to agent…"

    def close(self, target: SessionCloseTarget) -> SessionDisposition:
        target.connection_closed()
        return ClosedSessionDisposition()


class ClosedSessionDisposition(UnavailableSessionDisposition):
    status = SessionDisconnected("Session closed. Your draft is kept.")


@dataclass(frozen=True)
class HistoryOnlySessionDisposition(UnavailableSessionDisposition, ActiveSessionDisposition):
    """The owner runs another Core: history is open, input is refused."""

    owner: IncompatibleOwner

    @property
    def status(self) -> SessionDisconnected:
        return SessionDisconnected(self.owner.line())


@dataclass(frozen=True)
class FailedSessionDisposition(UnavailableSessionDisposition):
    """The terminal failure retained by this session's lifecycle owner."""

    failure: AgentFail

    @property
    def status(self) -> SessionDisconnected:
        return SessionDisconnected(
            self.failure.message, details=tuple(self.failure.details.splitlines())
        )

    async def present_failure(self, failure: AgentFail, view: FailurePresentation) -> None:
        if failure is self.failure:
            await failure.present_session(view)
        else:
            await super().present_failure(failure, view)


class RefusedSessionDisposition(FailedSessionDisposition):
    """A refused handshake leaves no session held by the process."""

    held_by_agent = False
