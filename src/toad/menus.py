"""Block-menu declarations and their captured native operations."""

from __future__ import annotations

import inspect
from abc import abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from agent_comms.nominal.declared_family import DeclaredFamily
from textual._callback import invoke
from textual.binding import ModeBinding
from textual.document._editing import EditingMode
from textual.keys import KeyDeclarationType, KeyInvocation
from textual.widget import Widget

from toad.line_blocks import LineLink
from toad.widget_actions import KeyFamilyMeta


class MenuConversation:
    """What a block-menu command may ask of the conversation it was opened in."""

    @abstractmethod
    def accepts_menu_owner(self, owner: Widget) -> bool: ...

    @abstractmethod
    def copy_block_to_clipboard(self) -> None: ...

    @abstractmethod
    def copy_block_to_prompt(self) -> None: ...

    @abstractmethod
    def export_block_to_svg(self) -> None: ...

    @abstractmethod
    def maximize_block(self) -> None: ...

    @abstractmethod
    async def interrupt_shell(self) -> None: ...

    @abstractmethod
    def open_line_link(self, link: LineLink) -> None: ...


class MenuOwner:
    """The control a command was captured by, and where its effect lands."""

    conversation: MenuConversation
    block: Widget

    @abstractmethod
    def activate_command(self, command: MenuCommand) -> None: ...


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

    def __call__(self, menu: MenuOwner) -> None:
        menu.activate_command(self)

    async def run(self, owner: MenuOwner) -> None:
        conversation = owner.conversation
        if conversation.accepts_menu_owner(owner.block):
            await invoke(self.apply, conversation)

    @abstractmethod
    def apply(self, conversation: MenuConversation) -> object: ...


class KeyedMenuCommand(MenuCommand, declared_name=None):
    """A command with a declared default key supplies it through inheritance."""

    key: ClassVar[str]

    @classmethod
    def default_keys(cls) -> tuple[str, ...]:
        return (cls.key,)


class CopyClipboardCommand(KeyedMenuCommand):
    key = "c"
    description = "[u]C[/]opy to clipboard"

    def apply(self, conversation: MenuConversation) -> None:
        conversation.copy_block_to_clipboard()


class CopyPromptCommand(KeyedMenuCommand):
    key = "p"
    description = "Co[u]p[/u]y to prompt"

    def apply(self, conversation: MenuConversation) -> None:
        conversation.copy_block_to_prompt()


class ExportSvgCommand(KeyedMenuCommand):
    key = "v"
    description = "Open as S[u]V[/]G"

    def apply(self, conversation: MenuConversation) -> None:
        conversation.export_block_to_svg()


class MaximizeBlockCommand(KeyedMenuCommand):
    key = "m"
    description = "[u]M[/u]aximize"

    def apply(self, conversation: MenuConversation) -> None:
        conversation.maximize_block()


class CopyThinkingCommand(CopyClipboardCommand):
    key = "y"
    description = "Copy thinking"


@dataclass(frozen=True)
class FocusBlockCommand(KeyedMenuCommand):
    block: Widget
    key = "f"
    description = "Focus"

    def apply(self, conversation: MenuConversation) -> None:
        self.block.focus()


class InterruptCommand(KeyedMenuCommand):
    key = "i"
    description = "Interrupt"

    async def apply(self, conversation: MenuConversation) -> None:
        await conversation.interrupt_shell()


@dataclass(frozen=True)
class OpenLinkCommand(MenuCommand, declared_name=None):
    link: LineLink

    def apply(self, conversation: MenuConversation) -> None:
        conversation.open_line_link(self.link)


class OpenSenderCommand(OpenLinkCommand, KeyedMenuCommand):
    key = "s"
    description = "Open [u]s[/u]ender"


class OpenDestinationCommand(OpenLinkCommand, KeyedMenuCommand):
    key = "d"
    description = "Open [u]d[/u]estination"
