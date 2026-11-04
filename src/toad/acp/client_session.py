"""One captured session authority for ACP client-side effects."""
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, NoReturn
from .queue_attachment import QueueActionRefused

if TYPE_CHECKING:
    from agent_comms.acp_extension import CoordinationChangedUpdate
    from .agent import Agent
    from .agent_session import SessionDisposition
    from .agent_controller import SessionBinding
from acp.exceptions import RequestError


@dataclass(frozen=True)
class ClientSessionRequest:
    agent: "Agent"
    session_id: str | None
    disposition: "SessionDisposition" = field(init=False)
    binding: "SessionBinding" = field(init=False)

    def __post_init__(self):
        object.__setattr__(self, 'disposition', self.agent.session.disposition)
        object.__setattr__(self, 'binding', self.agent.controller.session)

    @property
    def current(self):
        return (self.agent.controller.session is self.binding
                and self.agent.session.disposition is self.disposition
                and self.agent.session.accepts_session(self.session_id))

    @property
    def retired(self):
        return not self.current

    def require(self):
        if not self.current:
            raise RequestError.invalid_params({'details': 'ACP client request belongs to a retired session'})

    def unconfirmed(self, reason: str) -> None:
        """Ordinary input failure is presented by its existing failure publication."""


class QueueSessionRequest(ClientSessionRequest):
    """A queue mutation requires confirmation; an absent reply is never success."""

    def unconfirmed(self, reason: str) -> NoReturn:
        raise QueueActionRefused(f"Queue action not confirmed: {reason}. Inspect the queue before another action.")


@dataclass(frozen=True)
class OwnerRequest:
    """One original source and its independently captured physical authority."""

    coordination: "CoordinationChangedUpdate"
    authority: ClientSessionRequest

    @property
    def source_current(self) -> bool:
        return self.authority.agent.matches_source(
            self.coordination.wire_root, self.coordination.thread)

    @property
    def current(self) -> bool:
        return self.authority.current and self.source_current

    def require(self) -> None:
        if self.authority.retired:
            raise ValueError("The connected owner session retired; refresh its state.")
        if not self.source_current:
            raise ValueError("The owner identity changed while preparing the request.")


class ClientRequestOwner:
    def __init__(self, agent):
        self.agent = agent

    def session_request(self, session_id):
        request = ClientSessionRequest(self.agent, session_id)
        request.require()
        return request
