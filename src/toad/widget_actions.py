"""The Action family and its Textual dispatch projection."""
from __future__ import annotations

import inspect
from abc import abstractmethod
from collections.abc import Callable, Iterator, Mapping
from functools import partialmethod
from operator import or_
from types import MappingProxyType
from typing import ClassVar, Generic, Literal, Self, TypeVar

from agent_comms.command import Command
from agent_comms.declared_family import DeclaredFamily
from agent_comms.field_codec import FieldCodec, FieldPlan
from textual.binding import Binding
from textual.dom import DOMNode
from copy import replace
from dataclasses import dataclass

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


class DeclaredWidgetActions(DOMNode):
    """One family supplies both native dispatch and dynamic availability."""

    own_actions: ClassVar[tuple[type[Action], ...]] = ()

    @classmethod
    def declared_actions(cls) -> tuple[type[Action], ...]:
        """Capabilities and the widget's own family compose through its MRO."""
        return tuple(dict.fromkeys(
            member for base in cls.__mro__
            for family in base.__dict__.get("own_actions", ())
            for member in family.members_with(family)
        ))

    @classmethod
    def action_bindings(cls, declaration: type[Action]) -> tuple[Binding, ...]:
        return declaration.bindings()

    def __init_subclass__(cls, actions: tuple[type[Action], ...] = (), **kwargs):
        cls.own_actions = actions
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


class DismissAction(VisibleAction):
    """Close the current control."""
    keys = ("escape",)

    async def apply(self, context: DismissibleControl) -> None:
        context.dismiss_control()


class CursorAction(VisibleAction, affix="Action"):
    group = Binding.Group("Select")


class CursorUpAction(CursorAction):
    keys = ("up",)

    async def apply(self, context: MovesCursor) -> None:
        context.cursor_up()


class CursorDownAction(CursorAction):
    keys = ("down",)

    async def apply(self, context: MovesCursor) -> None:
        context.cursor_down()


class SubmitAction(VisibleAction):
    keys = ("enter",)

    async def apply(self, context: Submits) -> None:
        context.submit()


class SelectAction(VisibleAction):
    keys = ("enter",)

    async def apply(self, context: Selects) -> None:
        context.select()


class LaunchAction(VisibleAction):
    keys = ("space",)

    async def apply(self, context: Launches) -> None:
        await context.launch()


class ActivateAction(WidgetAction):
    keys = ("enter,space",)

    async def apply(self, context: Activates) -> None:
        context.activate()


class ToggleIrcAction(VisibleAction):
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


class FocusAction(VisibleAction, affix="Action"):
    group = Binding.Group("Focus")


class FocusNextAction(FocusAction):
    keys = ("tab",)

    async def apply(self, context: CyclesFocus) -> None:
        context.app.action_focus_next()


class FocusPreviousAction(FocusAction):
    keys = ("shift+tab",)

    async def apply(self, context: CyclesFocus) -> None:
        context.app.action_focus_previous()


class Dismisses(DeclaredWidgetActions, actions=(DismissAction,)):
    """The shared Escape binding."""


class DismissibleControl(Dismisses):
    @abstractmethod
    def dismiss_control(self) -> None:
        """Close this control without imposing a native screen result contract."""


class MovesCursor(DeclaredWidgetActions, actions=(CursorAction,)):

    @abstractmethod
    def cursor_up(self) -> None: ...

    @abstractmethod
    def cursor_down(self) -> None: ...


class Submits(DeclaredWidgetActions, actions=(SubmitAction,)):

    @abstractmethod
    def submit(self) -> None: ...


class Selects(DeclaredWidgetActions, actions=(SelectAction,)):

    @abstractmethod
    def select(self) -> None: ...


class Launches(DeclaredWidgetActions, actions=(LaunchAction,)):

    @abstractmethod
    async def launch(self) -> None: ...


class Activates(DeclaredWidgetActions, actions=(ActivateAction,)):

    @abstractmethod
    def activate(self) -> None: ...


class TogglesIrc(DeclaredWidgetActions, actions=(ToggleIrcAction,)):

    @abstractmethod
    async def toggle_irc(self) -> None: ...


class CyclesSessions(DeclaredWidgetActions, actions=(SessionNavigationAction,)):

    @abstractmethod
    def navigate_session(self, direction: Literal[-1, 1]) -> None: ...


class CyclesFocus(DeclaredWidgetActions, actions=(FocusAction,)):
    """Use the native DOM focus owner."""


Combiner = Callable[[bool, bool], bool]
PresentationScopes = Mapping[type, tuple[type[Action], ...]]


@dataclass(frozen=True)
class BindingStyle:
    field: FieldPlan
    combine: Combiner


def hide(current: bool, selected: bool) -> bool:
    return current and not selected


class ActionPresentation(DeclaredWidgetActions):
    binding_styles: ClassVar[tuple[BindingStyle, ...]] = ()
    scopes: ClassVar[PresentationScopes] = MappingProxyType({})

    def __init_subclass__(
        cls, fields: tuple[FieldPlan, ...] = (), combine: Combiner = or_,
        scopes: PresentationScopes = MappingProxyType({}),
        actions: tuple[type[Action], ...] = (), **kwargs: object,
    ) -> None:
        cls.binding_styles = tuple(BindingStyle(field, combine) for field in fields)
        cls.scopes = scopes
        super().__init_subclass__(actions=actions, **kwargs)

    @classmethod
    def present_binding(cls, declaration: type[Action], binding: Binding) -> Binding:
        scopes = {family: members for base in reversed(cls.__mro__)
                  for family, members in base.__dict__.get("scopes", {}).items()}
        for base in reversed(cls.__mro__):
            for style in base.__dict__.get("binding_styles", ()):
                selected = any(root in declaration.__mro__ for root in scopes.get(base, (Action,)))
                binding = replace(binding, **{
                    style.field.name: style.combine(bool(style.field.current(binding)), selected)
                })
        return binding

    @classmethod
    def action_bindings(cls, declaration: type[Action]) -> tuple[Binding, ...]:
        return tuple(cls.present_binding(declaration, binding)
                     for binding in super().action_bindings(declaration))


class PriorityActions(ActionPresentation,
                      fields=(FieldCodec.field_plan(Binding, "priority"),), combine=or_):
    """The selected actions take precedence over focused controls."""


class HiddenActions(ActionPresentation,
                    fields=(FieldCodec.field_plan(Binding, "show"),), combine=hide):
    """The selected actions stay out of the footer."""


class VisibleActions(ActionPresentation,
                     fields=(FieldCodec.field_plan(Binding, "show"),), combine=or_):
    """The selected actions are offered in the footer."""
