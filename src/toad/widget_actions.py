"""Native action declarations and their Textual dispatch projection."""
from abc import abstractmethod
from functools import partialmethod
from typing import ClassVar, Generic, TypeVar

from agent_comms.command import Command
from agent_comms.declared_family import DeclaredFamily
from agent_comms.field_codec import FieldCodec
from textual.binding import Binding


class KeyboundAction:
    key: ClassVar[str]
    description: ClassVar[str] = ""
    tooltip: ClassVar[str] = ""
    show: ClassVar[bool] = False
    priority: ClassVar[bool] = False
    system: ClassVar[bool] = False
    group: ClassVar[Binding.Group | None] = None
    key_display: ClassVar[str | None] = None

    @classmethod
    def binding(cls) -> Binding:
        return Binding(cls.key, cls.binding_name(), cls.description, tooltip=cls.tooltip,
                       show=cls.show, priority=cls.priority, system=cls.system,
                       group=cls.group, key_display=cls.key_display)

    @classmethod
    def bindings(cls):
        return (cls.binding(),)


class MenuAction:
    menu_order: ClassVar[int]
    menu_label: str

    @classmethod
    def menu_items(cls):
        yield cls()


Context = TypeVar("Context")


class NativeAction(Command, Generic[Context]):
    """Only the Textual boundary decodes an external action name."""

    binding_prefix: ClassVar[str] = ""

    @classmethod
    def binding_name(cls) -> str:
        return cls.binding_prefix + FieldCodec.encode(cls)

    @classmethod
    def parse(cls, parameters: tuple[object, ...]):
        if parameters:
            raise ValueError(f"{cls.declared_name} takes no parameters")
        return cls()

    @classmethod
    def bindings(cls):
        return ()

    def available(self, context: Context) -> bool | None:
        return True

    @abstractmethod
    async def apply(self, context: Context) -> None: ...


class ApplicationAction(NativeAction, DeclaredFamily, affix="Action"):
    """Application action membership and native namespace belong here."""

    binding_prefix = "app."

    @classmethod
    def menu(cls):
        return tuple((action, action.menu_label)
                     for kind in sorted(cls.members_with(MenuAction), key=lambda kind: kind.menu_order)
                     for action in kind.menu_items())


class VimApplicationAction(KeyboundAction, ApplicationAction):
    def available(self, app):
        return app.settings.ui.vim_keys and app.current_mode == "workspace"


class VimHintsAction(VimApplicationAction):
    key = "f"

    async def apply(self, app):
        await app.screen.action_show_hints()


class DeclaredWidgetActions:
    """One family supplies both native dispatch and dynamic availability."""

    def __init_subclass__(cls, **kwargs):
        if "ACTIONS" not in cls.__dict__:
            super().__init_subclass__(**kwargs)
            return
        actions = cls.ACTIONS
        cls.BINDINGS = [*cls.__dict__.get("BINDINGS", ()),
                        *(binding for declaration in actions.members_with(actions)
                          for binding in declaration.bindings())]
        for declaration in actions.members_with(actions):
            setattr(cls, f"action_{declaration.declared_name}",
                    partialmethod(cls._run_declared_action, declaration))
        super().__init_subclass__(**kwargs)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        try:
            declaration = self.ACTIONS.decode(action)
        except ValueError:
            return super().check_action(action, parameters)
        return declaration.parse(parameters).available(self)

    async def _run_declared_action(self, declaration, *parameters) -> None:
        command = declaration.parse(parameters)
        if command.available(self):
            await command.apply(self)
