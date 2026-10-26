"""Record actual ACP loads; a new-session call has a different session ID."""
from pathlib import Path
from acp.schema import AgentCapabilities, InitializeResponse, LoadSessionResponse
from base import Peer


class LoadExisting(Peer):
    async def initialize(self, protocol_version, **kwargs):
        return InitializeResponse(protocolVersion=protocol_version,
                                  agentCapabilities=AgentCapabilities(loadSession=True))

    async def load_session(self, session_id, cwd, **kwargs):
        self.project = Path(cwd)
        self.record(loaded=session_id)
        return LoadSessionResponse()


if __name__ == '__main__':
    LoadExisting.main()
