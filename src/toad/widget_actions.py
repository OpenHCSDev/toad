"""The Action family and its Textual dispatch projection."""
import inspect
from abc import abstractmethod
from collections.abc import Iterator
from functools import partialmethod
from typing import ClassVar, Generic, Self, TypeVar

from agent_comms.command import Command
from agent_comms.declared_family import DeclaredFamily
from agent_comms.field_codec import FieldCodec
from textual.binding import Binding

Context = TypeVar("Context")


class DeclaredTitle:
    """A member's title is its declared name in words until a class on its MRO declares one."""

    def __get__(self, instance, owner) -> str:
        return owner.declared_name.replace("_", " ").capitalize()


class Action(Command, DeclaredFamily, Generic[Context], affix="Action"):
    """Only the Textual boundary decodes an external action name. A member declares its
    keys, and its title and docstring are the only text any view shows for it."""

    keys: ClassVar[tuple[str, ...]] = ()
    title: ClassVar[str] = DeclaredTitle()
    show: ClassVar[bool] = False
    priority: ClassVar[bool] = False
    system: ClassVar[bool] = False
    group: ClassVar[Binding.Group | None] = None
    key_display: ClassVar[str | None] = None
    binding_prefix: ClassVar[str] = ""

    @classmethod
    def summary(cls) -> str:
        """The nearest docstring a member declares; the family roots document code, not keys."""
        root = cls.family_root()
        return next((inspect.cleandoc(base.__doc__) for base in cls.__mro__
                     if issubclass(base, root) and base is not root and base.__doc__), "")

    @classmethod
    def binding_name(cls) -> str:
        return cls.binding_prefix + FieldCodec.encode(cls)

    @classmethod
    def bindings(cls) -> tuple[Binding, ...]:
        return tuple(Binding(key, cls.binding_name(), cls.title, tooltip=cls.summary(),
                             show=cls.show, priority=cls.priority, system=cls.system,
                             group=cls.group, key_display=cls.key_display, id=cls.declared_name)
                     for key in cls.keys)

    @classmethod
    def parse(cls, parameters: tuple[object, ...]):
        if parameters:
            raise ValueError(f"{cls.declared_name} takes no parameters")
        return cls()

    @classmethod
    def offered(cls, context: Context) -> Iterator[Self]:
        """What the menu and the palette offer for this member: itself, where it is available."""
        command = cls()
        if command.available(context):
            yield command

    def label(self, context: Context) -> str:
        """A state-dependent title overrides this; every other member shows its title."""
        return self.title

    def available(self, context: Context) -> bool | None:
        return True

    @abstractmethod
    async def apply(self, context: Context) -> None: ...


class System:
    """Only its key reaches the action: no menu, palette or key panel shows it."""

    system: ClassVar[bool] = True

    @classmethod
    def offered(cls, context) -> Iterator[Action]:
        return iter(())


class YieldingKey:
    """An application key that any binding closer to the focus replaces: it answers only
    where nothing local claims the key, so the claim is no conflict."""


class ApplicationAction(Action, affix="Action"):
    binding_prefix = "app."

    @classmethod
    def menu(cls, app):
        """Every offered member under its label, in declaration order."""
        return tuple((command, command.label(app))
                     for member in cls.members_with(cls) for command in member.offered(app))


class VimApplicationAction(YieldingKey, ApplicationAction):
    def available(self, app):
        return app.settings.ui.vim_keys and app.current_mode == "workspace"


class VimHintsAction(VimApplicationAction):
    """Label every clickable widget with a key to reach it."""

    keys = ("f", "ctrl+f")

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
        actions = self.ACTIONS
        if action not in actions.names():
            return super().check_action(action, parameters)
        return actions.member_named(action).parse(parameters).available(self)

    async def _run_declared_action(self, declaration, *parameters) -> None:
        command = declaration.parse(parameters)
        if command.available(self):
            await command.apply(self)
