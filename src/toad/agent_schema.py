"""Agent catalog definitions, decoded once from TOML or saved metadata."""
from __future__ import annotations
from dataclasses import dataclass, field
import shlex
from acp import schema as acp_protocol
from typing import Annotated, Literal
from agent_comms.nominal.declared_family import DeclaredFamily
from agent_comms.nominal.field_codec import FieldCodec, TextRepresentation, WireName
from toad.platform import Platform


class AgentKind(DeclaredFamily, affix='AgentKind'):
    heading: str
    description: str

    @classmethod
    def section(cls):
        return cls


class ChatAgentKind(AgentKind):
    @classmethod
    def section(cls):
        return ChatAgentKind

    heading = 'Chat & Assistants'
    description = 'Biddi-biddi-biddi'


class AssistantAgentKind(ChatAgentKind):
    pass


class CodingAgentKind(AgentKind):
    heading = 'Coding agents'
    description = 'Build software with AI'


class AgentKindText(TextRepresentation):
    @classmethod
    def from_text(cls, value):
        return AgentKind.member_named(value)

    @classmethod
    def encode(cls, value):
        return value.declared_name


@dataclass(frozen=True)
class Command:
    description: str
    command: str
    bootstrap_uv: bool = False

    @classmethod
    def for_login(
        cls, platform: type[Platform], definition: AgentDefinition,
        method: acp_protocol.TerminalAuthMethod,
    ) -> Command:
        """Acquire the catalog command from the actual terminal-auth declaration."""
        command = platform.select(definition.run_command)
        if not command:
            raise ValueError("This agent has no configured login program")
        arguments = method.args or []
        command = command + (" " + shlex.join(arguments) if arguments else "")
        return cls(method.name, command)


@dataclass(frozen=True)
class AgentDefinition:
    identity: str
    name: str
    run_command: dict[str, str]
    short_name: str = ''
    protocol: Literal['acp'] = 'acp'
    accepts_comms_root: bool = False
    kind: Annotated[type[AgentKind], AgentKindText, WireName("type")] = CodingAgentKind
    url: str = ''
    author_name: str = ''
    author_url: str = ''
    publisher_name: str = ''
    publisher_url: str = ''
    description: str = ''
    tags: list[str] = field(default_factory=list)
    help: str = ''
    welcome: str | None = None
    actions: dict[str, dict[str, Command]] = field(default_factory=dict)
    active: bool = True
    recommended: bool = False

    def commands_for(self, platform: type[Platform]) -> dict[str, Command]:
        return platform.select(self.actions) or {}

    @classmethod
    def decode(cls, value: object) -> AgentDefinition:
        return FieldCodec.decode(cls, value)
