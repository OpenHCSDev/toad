"""The Action family and its Textual dispatch projection."""
from __future__ import annotations

import inspect
from abc import abstractmethod
from collections.abc import Awaitable, Iterator
from functools import partialmethod
from typing import ClassVar, Generic, Literal, Self, TypeVar

from agent_comms.command import Command
from agent_comms.declared_family import DeclaredFamily
from agent_comms.field_codec import FieldCodec
from textual.binding import Binding
from textual.dom import DOMNode
from textual._callback import invoke
from dataclasses import replace

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
    def declarations(cls) -> tuple[type[Self], ...]:
        return cls.members_with(cls)

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

    ACTIONS: ClassVar[type[Action]]

    @classmethod
    def declared_actions(cls) -> tuple[type[Action], ...]:
        """Capabilities and the widget's own family compose through its MRO."""
        members = tuple(dict.fromkeys(
            member for base in cls.__mro__
            if issubclass(base, DeclaredWidgetActions) and "ACTIONS" in vars(base)
            for member in base.ACTIONS.declarations()
        ))
        inherited = {base for member in members for base in member.__mro__[1:]}
        return tuple(member for member in members if member not in inherited)

    @classmethod
    def action_bindings(cls, declaration: type[Action]) -> tuple[Binding, ...]:
        return declaration.bindings()

    def __init_subclass__(cls, **kwargs):
        declarations = cls.declared_actions()
        cls.BINDINGS = [*cls.__dict__.get("BINDINGS", ()),
                        *(binding for declaration in declarations
                          for binding in cls.action_bindings(declaration))]
        for declaration in declarations:
            setattr(cls, f"action_{declaration.declared_name}",
                    partialmethod(cls._run_declared_action, declaration))
        super().__init_subclass__(**kwargs)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        for declaration in self.declared_actions():
            if action == declaration.declared_name:
                return declaration.parse(parameters).available(self)
        return super().check_action(action, parameters)

    async def _run_declared_action(self, declaration, *parameters) -> None:
        command = declaration.parse(parameters)
        if command.available(self):
            await command.apply(self)


class WidgetAction(Action, affix="Action"):
    """Keyboard operations on the focused widget, distinct from configured commands."""


class VisibleAction(WidgetAction):
    show = True


class SingleAction:
    """A capability selects this declaration, not every contextual specialization."""

    @classmethod
    def declarations(cls) -> tuple[type[Self], ...]:
        return (cls,)


class ActionGroup(Generic[Context]):
    """A family root groups executable members; it has no operation of its own."""

    async def apply(self, context: Context) -> None:
        pass


class DismissAction(SingleAction, VisibleAction):
    """Close the current control."""
    keys = ("escape",)

    async def apply(self, context: Dismisses) -> None:
        context.dismiss_control()


class HiddenDismissAction(DismissAction):
    show = False
    title = DismissAction.title


class CursorAction(ActionGroup["MovesCursor"], VisibleAction, affix="Action"):
    group = Binding.Group("Select")


class CursorUpAction(CursorAction):
    keys = ("up",)

    async def apply(self, context: MovesCursor) -> None:
        context.cursor_up()


class CursorDownAction(CursorAction):
    keys = ("down",)

    async def apply(self, context: MovesCursor) -> None:
        context.cursor_down()


class SubmitAction(SingleAction, VisibleAction):
    keys = ("enter",)

    async def apply(self, context: Submits) -> None:
        await invoke(context.submit)


class HiddenSubmitAction(SubmitAction):
    show = False
    title = SubmitAction.title


class SelectAction(SingleAction, VisibleAction):
    keys = ("enter",)

    async def apply(self, context: Selects) -> None:
        context.select()


class LaunchAction(SingleAction, VisibleAction):
    keys = ("space",)

    async def apply(self, context: Launches) -> None:
        await invoke(context.launch)


class PriorityLaunchAction(LaunchAction):
    """The modal's launch key wins over its focused controls; Escape still yields."""
    priority = True
    title = LaunchAction.title


class ActivateAction(SingleAction, WidgetAction):
    keys = ("enter,space",)

    async def apply(self, context: Activates) -> None:
        context.activate()


class VisibleActivateAction(ActivateAction):
    show = True
    title = ActivateAction.title


class ToggleIrcAction(SingleAction, VisibleAction):
    title = "IRC view"
    keys = ("ctrl+g",)

    async def apply(self, context: TogglesIrc) -> None:
        await context.toggle_irc()


SESSION_NAVIGATION_GROUP = Binding.Group(description="Sessions")


class SessionNavigationAction(VisibleAction, affix="Action"):
    group = SESSION_NAVIGATION_GROUP
    direction: ClassVar[Literal[-1, 1]]

    async def apply(self, context: CyclesSessions) -> None:
        context.navigate_session(self.direction)


class SessionPreviousAction(SessionNavigationAction):
    keys = ("ctrl+left_square_bracket",)
    direction = -1


class SessionNextAction(SessionNavigationAction):
    keys = ("ctrl+right_square_bracket",)
    direction = +1


class FocusAction(ActionGroup["CyclesFocus"], VisibleAction, affix="Action"):
    group = Binding.Group("Focus")


class FocusNextAction(FocusAction):
    keys = ("tab",)

    async def apply(self, context: CyclesFocus) -> None:
        context.app.action_focus_next()


class FocusPreviousAction(FocusAction):
    keys = ("shift+tab",)

    async def apply(self, context: CyclesFocus) -> None:
        context.app.action_focus_previous()


class Dismisses(DeclaredWidgetActions):
    ACTIONS: ClassVar[type[Action]] = DismissAction

    @abstractmethod
    def dismiss_control(self) -> None:
        """Close this control without imposing a native screen result contract."""


class HiddenDismisses(Dismisses):
    ACTIONS: ClassVar[type[Action]] = HiddenDismissAction


class MovesCursor(DeclaredWidgetActions):
    ACTIONS: ClassVar[type[Action]] = CursorAction

    @abstractmethod
    def cursor_up(self) -> None: ...

    @abstractmethod
    def cursor_down(self) -> None: ...


class Submits(DeclaredWidgetActions):
    ACTIONS: ClassVar[type[Action]] = SubmitAction

    @abstractmethod
    def submit(self) -> None: ...


class HiddenSubmits(Submits):
    ACTIONS: ClassVar[type[Action]] = HiddenSubmitAction


class Selects(DeclaredWidgetActions):
    ACTIONS: ClassVar[type[Action]] = SelectAction

    @abstractmethod
    def select(self) -> None: ...


class Launches(DeclaredWidgetActions):
    ACTIONS: ClassVar[type[Action]] = LaunchAction

    @abstractmethod
    def launch(self) -> Awaitable[None] | None: ...


class PriorityLaunches(Launches):
    ACTIONS: ClassVar[type[Action]] = PriorityLaunchAction


class Activates(DeclaredWidgetActions):
    ACTIONS: ClassVar[type[Action]] = ActivateAction

    @abstractmethod
    def activate(self) -> None: ...


class VisibleActivates(Activates):
    ACTIONS: ClassVar[type[Action]] = VisibleActivateAction


class TogglesIrc(DeclaredWidgetActions):
    ACTIONS: ClassVar[type[Action]] = ToggleIrcAction

    @abstractmethod
    async def toggle_irc(self) -> None: ...


class CyclesSessions(DeclaredWidgetActions):
    ACTIONS: ClassVar[type[Action]] = SessionNavigationAction

    @abstractmethod
    def navigate_session(self, direction: Literal[-1, 1]) -> None: ...


class CyclesFocus(DeclaredWidgetActions, DOMNode):
    ACTIONS: ClassVar[type[Action]] = FocusAction


class PriorityActions(DeclaredWidgetActions):
    """A popup's declared keys take precedence over the editor underneath it."""

    @classmethod
    def action_bindings(cls, declaration: type[Action]) -> tuple[Binding, ...]:
        return tuple(replace(binding, priority=True)
                     for binding in super().action_bindings(declaration))


class HiddenActions(DeclaredWidgetActions):
    """A compact control keeps its actions out of the footer."""

    @classmethod
    def action_bindings(cls, declaration: type[Action]) -> tuple[Binding, ...]:
        return tuple(replace(binding, show=False)
                     for binding in super().action_bindings(declaration))
