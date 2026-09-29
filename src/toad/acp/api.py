# mypy: disable-error-code="empty-body"
"""
ACP remote API
"""

from toad import jsonrpc
from acp import schema

API = jsonrpc.API()


@API.method()
def authenticate(methodId: str) -> schema.AuthenticateResponse:
    """Use an agent-advertised protocol authentication method."""
    ...


@API.method()
def initialize(
    protocolVersion: int,
    clientCapabilities: schema.ClientCapabilities,
    clientInfo: schema.Implementation,
) -> schema.InitializeResponse:
    """https://agentclientprotocol.com/protocol/initialization"""
    ...


@API.method(name="session/new")
def session_new(
    cwd: str, mcpServers: schema.NewSessionRequest.model_fields["mcp_servers"].annotation
) -> schema.NewSessionResponse:
    """https://agentclientprotocol.com/protocol/session-setup#session-id"""
    ...


@API.method(name="session/load")
def session_load(
    cwd: str, mcpServers: schema.LoadSessionRequest.model_fields["mcp_servers"].annotation, sessionId: str
) -> schema.LoadSessionResponse:
    """https://agentclientprotocol.com/protocol/session-setup#loading-a-session"""
    ...


@API.notification(name="session/cancel")
def session_cancel(sessionId: str, _meta: dict):
    """https://agentclientprotocol.com/protocol/prompt-turn#cancellation"""
    ...


@API.method(name="session/prompt")
def session_prompt(
    prompt: schema.PromptRequest.model_fields["prompt"].annotation, sessionId: str, _meta: dict | None = None
) -> schema.PromptResponse:
    """https://agentclientprotocol.com/protocol/prompt-turn#1-user-message"""
    ...


@API.method(name="session/set_mode")
def session_set_mode(sessionId: str, modeId: str) -> schema.SetSessionModeResponse:
    """https://agentclientprotocol.com/protocol/session-modes#from-the-client"""
    ...


@API.method(name="session/set_config_option")
def session_set_config_option(
    sessionId: str, configId: str, value: str
) -> schema.SetSessionConfigOptionResponse:
    """https://agentclientprotocol.com/protocol/session-config-options"""
    ...
