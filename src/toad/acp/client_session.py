"""One captured session authority for ACP client-side effects."""
from dataclasses import dataclass, field
from agent_comms.declared_family import DeclaredFamily
from toad.jsonrpc import InvalidParams


@dataclass(frozen=True)
class ClientSessionRequest:
    agent: object
    session_id: str
    disposition: object = field(init=False)

    def __post_init__(self):
        object.__setattr__(self, 'disposition', self.agent.process.disposition)

    @property
    def current(self):
        return (self.agent.process.disposition is self.disposition
                and self.agent.process.accepts_session(self.session_id))

    @property
    def retired(self):
        return not self.current

    def require(self):
        if not self.current:
            raise InvalidParams('ACP client request belongs to a retired session')


class ClientRequestOwner(DeclaredFamily, affix='ClientRequestOwner'):
    def __init__(self, agent):
        self.agent = agent

    @classmethod
    def resolve(cls, agent):
        return cls(agent)

    def session_request(self, session_id):
        request = ClientSessionRequest(self.agent, session_id)
        request.require()
        return request
