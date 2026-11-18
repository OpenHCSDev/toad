"""Block-menu declarations and their captured native operations."""

from __future__ import annotations

import inspect
from abc import abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from agent_comms.nominal.declared_family import DeclaredFamily
from textual._callback import invoke
from textual.binding import ModeBinding

from formbridge.key_declarations import KeyDeclarationType, KeyInvocation, TextEntryMode
from textual.widget import Widget

from toad.client.line_blocks import LineLink
from toad.message_rows import MessageRow
from toad.client.application_actions import KeyFamilyMeta


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

    @classmethod
    def offered_for(cls, target: object) -> bool:
        """Whether this command belongs in a block menu for ``target``. Subclasses whose
        applicability depends on target state override this; the default makes a no-arg
        command apply to any target."""
        return True

    def bindings(self, mode: type[TextEntryMode]) -> tuple[ModeBinding, ...]:
        return tuple(
            binding
            for key in type(self).default_keys()
            for binding in MenuBinding(
                key=key,
                action=self,
                mode=TextEntryMode,
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

    @classmethod
    def offered_for(cls, target: object) -> bool:
        return bool(target.allow_maximize)

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


def message_menu(row: MessageRow) -> tuple[MenuCommand, ...]:
    """What the cursor's menu offers on a bus message, wherever it is drawn."""
    return (OpenSenderCommand(row.sender),
            *(OpenDestinationCommand(row.name(target).link) for target in row.route.targets[:1]))


def standard_commands(target: object) -> tuple[MenuCommand, ...]:
    """The no-arg MenuCommand subclasses from the family that apply to ``target``,
    instantiated once each. Keeps the menu derived from the family: a new command
    declared in this module reaches every frontend without edits at a call site."""
    offered: list[MenuCommand] = []
    for cls in MenuCommand.members_with(MenuCommand):
        try:
            sig = inspect.signature(cls)
        except (TypeError, ValueError):
            continue
        required = tuple(
            parameter for parameter in sig.parameters.values()
            if parameter.default is inspect.Parameter.empty
            and parameter.kind in (inspect.Parameter.POSITIONAL_ONLY,
                                   inspect.Parameter.POSITIONAL_OR_KEYWORD,
                                   inspect.Parameter.KEYWORD_ONLY)
        )
        if required:
            continue
        if not cls.offered_for(target):
            continue
        try:
            offered.append(cls())
        except TypeError:
            continue
    return tuple(offered)
