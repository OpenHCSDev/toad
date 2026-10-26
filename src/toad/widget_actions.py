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

    @classmethod
    def declared_actions(cls) -> tuple[type[Action], ...]:
        """Capabilities and the widget's own family compose through its MRO."""
        return tuple(dict.fromkeys(
            member for base in cls.__mro__ if "ACTIONS" in base.__dict__
            for family in (base.__dict__["ACTIONS"],)
            for member in family.members_with(family)
        ))

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


class DismissAction(VisibleAction):
    """Close the current control."""
    keys = ("escape",)

    async def apply(self, context):
        await invoke(context.dismiss)


class CursorAction(VisibleAction, affix="Action"):
    group = Binding.Group("Select")


class CursorUpAction(CursorAction):
    keys = ("up",)

    async def apply(self, context):
        context.cursor_up()


class CursorDownAction(CursorAction):
    keys = ("down",)

    async def apply(self, context):
        context.cursor_down()


class SubmitAction(VisibleAction):
    keys = ("enter",)

    async def apply(self, context):
        await invoke(context.submit)


class SelectAction(VisibleAction):
    keys = ("enter",)

    async def apply(self, context):
        context.select()


class LaunchAction(VisibleAction):
    keys = ("space",)

    async def apply(self, context):
        await invoke(context.launch)


class ActivateAction(WidgetAction):
    keys = ("enter,space",)

    async def apply(self, context):
        context.activate()


class ToggleIrcAction(VisibleAction):
    title = "IRC view"
    keys = ("ctrl+g",)

    async def apply(self, context):
        await context.toggle_irc()


SESSION_NAVIGATION_GROUP = Binding.Group(description="Sessions")


class SessionNavigationAction(VisibleAction, affix="Action"):
    group = SESSION_NAVIGATION_GROUP
    direction: ClassVar[int]

    async def apply(self, context):
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

    async def apply(self, context):
        context.app.action_focus_next()


class FocusPreviousAction(FocusAction):
    keys = ("shift+tab",)

    async def apply(self, context):
        context.app.action_focus_previous()


class Dismisses(DeclaredWidgetActions):
    ACTIONS = DismissAction


class MovesCursor(DeclaredWidgetActions):
    ACTIONS = CursorAction


class Submits(DeclaredWidgetActions):
    ACTIONS = SubmitAction


class Selects(DeclaredWidgetActions):
    ACTIONS = SelectAction


class Launches(DeclaredWidgetActions):
    ACTIONS = LaunchAction


class Activates(DeclaredWidgetActions):
    ACTIONS = ActivateAction


class TogglesIrc(DeclaredWidgetActions):
    ACTIONS = ToggleIrcAction


class CyclesSessions(DeclaredWidgetActions):
    ACTIONS = SessionNavigationAction


class CyclesFocus(DeclaredWidgetActions):
    ACTIONS = FocusAction


class PriorityActions(DeclaredWidgetActions):
    """A popup's declared keys take precedence over the editor underneath it."""

    @classmethod
    def action_bindings(cls, declaration):
        return tuple(replace(binding, priority=True)
                     for binding in super().action_bindings(declaration))


class HiddenActions(DeclaredWidgetActions):
    """A compact control keeps its actions out of the footer."""

    @classmethod
    def action_bindings(cls, declaration):
        return tuple(replace(binding, show=False)
                     for binding in super().action_bindings(declaration))
