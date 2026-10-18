"""One captured session authority for ACP client-side effects."""
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
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


class ClientRequestOwner:
    def __init__(self, agent):
        self.agent = agent

    def session_request(self, session_id):
        request = ClientSessionRequest(self.agent, session_id)
        request.require()
        return request
