"""Agent catalog definitions, decoded once from TOML or saved metadata."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Annotated, Literal
from agent_comms.declared_family import DeclaredFamily
from agent_comms.field_codec import FieldCodec, TextRepresentation

type OS = Literal['macos', 'linux', 'windows', '*']


class AgentKind(DeclaredFamily, affix='AgentKind'):
    heading: str
    description: str

    @classmethod
    def section(cls):
        return cls

    @classmethod
    def compose(cls, agents):
        from textual import containers, widgets
        from toad.screens.store import AgentGridSelect, AgentItem
        if not agents:
            return
        yield widgets.Static(f'[$text-warning u]{cls.heading}[/] [$text-secondary i]{cls.description}', classes='heading')
        with containers.VerticalGroup():
            with AgentGridSelect(classes='agents-picker', min_column_width=40):
                for agent in agents:
                    yield AgentItem(agent)


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
        return AgentKind.decode(value)

    @classmethod
    def encode(cls, value):
        return value.declared_name


@dataclass(frozen=True)
class Command:
    description: str
    command: str
    bootstrap_uv: bool = False

    def bind(self, name: str):
        """Bind this original record to a native catalog operation."""
        from toad.catalog_actions import CatalogCommandAction, RunAction
        try:
            # External catalog IDs permit hyphens as well as underscores.
            # Keep the original ID on the bound operation; only this lookup
            # uses the declaration's native snake-case spelling.
            operation = CatalogCommandAction.decode(name.replace('-', '_'))
        except ValueError:
            # Configured command IDs are open: arbitrary scripts have ordinary
            # completion behavior, not an implicit installation/login policy.
            operation = RunAction
        return operation(name, self)


@dataclass(frozen=True)
class AgentDefinition:
    identity: str
    name: str
    run_command: dict[str, str]
    short_name: str = ''
    protocol: Literal['acp'] = 'acp'
    kind: Annotated[type[AgentKind], AgentKindText] = field(default=CodingAgentKind, metadata={'wire_name': 'type'})
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

    def commands_for(self, platform: OS) -> dict[str, Command]:
        """Select the catalog's exact platform or its declared wildcard."""
        return self.actions.get(platform, self.actions.get('*', {}))

    @classmethod
    def decode(cls, value: object) -> AgentDefinition:
        return FieldCodec.decode(cls, value)
