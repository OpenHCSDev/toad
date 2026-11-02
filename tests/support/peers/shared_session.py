"""A real SDK peer that can keep two loaded sessions on one process."""
from acp.schema import (
    AgentCapabilities, CloseSessionResponse, InitializeResponse, LoadSessionResponse,
    SessionCapabilities, SessionCloseCapabilities,
)
from base import Peer


class SharedSessionPeer(Peer):
    async def initialize(self, protocol_version: int, **kwargs: object) -> InitializeResponse:
        response = await super().initialize(protocol_version, **kwargs)
        response.agent_capabilities = AgentCapabilities(
            loadSession=True, sessionCapabilities=SessionCapabilities(close=SessionCloseCapabilities()),
        )
        return response

    async def load_session(self, cwd: str, session_id: str, **kwargs: object) -> LoadSessionResponse:
        await super().new_session(cwd, **kwargs)
        self.record(loaded=session_id)
        return LoadSessionResponse()

    async def close_session(self, session_id: str, **kwargs: object) -> CloseSessionResponse:
        self.record(closed=session_id)
        return CloseSessionResponse()


if __name__ == "__main__":
    SharedSessionPeer.main()
