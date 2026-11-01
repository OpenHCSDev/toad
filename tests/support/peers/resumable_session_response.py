"""The response peer's load capability, through the real ACP SDK connection."""
from acp.schema import AgentCapabilities, LoadSessionResponse
from session_response import SessionResponsePeer


class ResumableSessionResponsePeer(SessionResponsePeer):
    async def initialize(self, protocol_version: int, **kwargs):
        response = await super().initialize(protocol_version, **kwargs)
        return response.model_copy(update={"agent_capabilities": AgentCapabilities(loadSession=True)})

    async def load_session(self, cwd: str, session_id: str, **kwargs):
        response = await self.new_session(cwd, **kwargs)
        return LoadSessionResponse(_meta=response.field_meta, configOptions=response.config_options)


if __name__ == "__main__":
    ResumableSessionResponsePeer.main()
