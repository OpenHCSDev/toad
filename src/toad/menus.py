"""Block-menu declarations and their captured native operations."""

from __future__ import annotations

import inspect
from abc import abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from agent_comms.declared_family import DeclaredFamily
from textual._callback import invoke
from textual.binding import ModeBinding
from textual.document._editing import EditingMode
from textual.keys import KeyDeclarationType, KeyInvocation
from textual.widget import Widget

from toad.widget_actions import ExclusiveKeys, KeyFamilyMeta

if TYPE_CHECKING:
    from toad.line_blocks import LineLink
    from toad.widgets.conversation import Conversation
    from toad.widgets.menu import Menu
    from toad.widgets.tool_call import ToolCall


class MenuDeclaration(KeyFamilyMeta, KeyInvocation):
    """The declaration, not captured instance parameters, owns keyboard identity."""

    description: str

    def key_identity(cls) -> str:
        return KeyInvocation.qualified(cls)

    def key_title(cls) -> str:
        return cls.description

    def key_summary(cls) -> str:
        return inspect.cleandoc(cls.__doc__ or "")

    def key_system(cls) -> bool:
        return False

    def permits_invocation_overlap(cls, other: KeyInvocation) -> bool:
        return other.overlaps_declaration(cls)

    def overlaps_declaration(cls, other: KeyDeclarationType) -> bool:
        return cls.permits_key_overlap(other)


class MenuBinding(ModeBinding):
    action: MenuCommand

    @property
    def invocation(self) -> KeyInvocation:
        return type(self.action)


class MenuCommand(DeclaredFamily, metaclass=MenuDeclaration, affix="Command"):
    """Every block operation checks the captured menu context before acting."""

    description: ClassVar[str]

    @classmethod
    def default_keys(cls) -> tuple[str, ...]:
        return ()

    def bindings(self, mode: type[EditingMode]) -> tuple[ModeBinding, ...]:
        return tuple(
            binding
            for key in type(self).default_keys()
            for binding in MenuBinding(
                key=key,
                action=self,
                mode=EditingMode,
                description=self.description,
                show=False,
            ).for_mode(mode)
        )

    def __call__(self, menu: Menu) -> None:
        menu.activate_command(self)

    async def run(self, owner: Menu) -> None:
        conversation = owner.conversation
        if conversation.is_current_session and conversation.navigation.accepts_menu_owner(
            owner.block
        ):
            await invoke(self.apply, conversation)

    @abstractmethod
    def apply(self, conversation: Conversation) -> object: ...


class KeyedMenuCommand(MenuCommand, declared_name=None):
    """A command with a declared default key supplies it through inheritance."""

    key: ClassVar[str]

    @classmethod
    def default_keys(cls) -> tuple[str, ...]:
        return (cls.key,)


class CopyClipboardCommand(KeyedMenuCommand):
    key = "c"
    description = "[u]C[/]opy to clipboard"

    def apply(self, conversation: Conversation) -> None:
        conversation.action_copy_to_clipboard()


class CopyPromptCommand(KeyedMenuCommand):
    key = "p"
    description = "Co[u]p[/u]y to prompt"

    def apply(self, conversation: Conversation) -> None:
        conversation.action_copy_to_prompt()


class ExportSvgCommand(KeyedMenuCommand):
    key = "v"
    description = "Open as S[u]V[/]G"

    def apply(self, conversation: Conversation) -> None:
        conversation.action_export_to_svg()


class MaximizeBlockCommand(KeyedMenuCommand):
    key = "m"
    description = "[u]M[/u]aximize"

    def apply(self, conversation: Conversation) -> None:
        conversation.action_maximize_block()


class CopyThinkingCommand(CopyClipboardCommand):
    key = "y"
    description = "Copy thinking"


@dataclass(frozen=True)
class FocusBlockCommand(KeyedMenuCommand):
    block: Widget
    key = "f"
    description = "Focus"

    def apply(self, conversation: Conversation) -> None:
        self.block.focus()


class InterruptCommand(KeyedMenuCommand):
    key = "i"
    description = "Interrupt"

    async def apply(self, conversation: Conversation) -> None:
        await conversation.interrupt_shell()


class ExpansionCommand(ExclusiveKeys, KeyedMenuCommand, declared_name=None):
    """Collapse and expand alternate on one block, so they share their key."""


@dataclass(frozen=True)
class CollapseCommand(ExpansionCommand):
    block: ToolCall
    key = "x"
    description = "Collapse"

    def apply(self, conversation: Conversation) -> None:
        self.block.collapse_block()


@dataclass(frozen=True)
class ExpandCommand(ExpansionCommand):
    block: ToolCall
    key = "x"
    description = "Expand"

    def apply(self, conversation: Conversation) -> None:
        self.block.expand_block()


@dataclass(frozen=True)
class OpenLinkCommand(MenuCommand, declared_name=None):
    link: LineLink

    def apply(self, conversation: Conversation) -> None:
        conversation.transcript.binding.history.action_open(self.link)


class OpenSenderCommand(OpenLinkCommand, KeyedMenuCommand):
    key = "s"
    description = "Open [u]s[/u]ender"


class OpenDestinationCommand(OpenLinkCommand, KeyedMenuCommand):
    key = "d"
    description = "Open [u]d[/u]estination"
