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
from agent_comms.nominal.declared_family import DeclaredFamily
from agent_comms.nominal.field_codec import FieldCodec, FieldPlan
from textual.binding import Binding, BindingsMap, CommandBinding, ModeBinding
from textual import events
from textual._activation import PrimaryActivation
from textual._callback import invoke
from textual.keys import KeyDeclaration
from textual.widgets.text_area import EditingMode
from textual.dom import DOMNode
from toad.app_node import ToadNode
from copy import replace
from dataclasses import dataclass

Context = TypeVar("Context", bound=DOMNode)


class Action(KeyDeclaration[Context], Command, DeclaredFamily, Generic[Context], affix="Action"):
    """Only the Textual boundary decodes an external action name. A member declares its
    keys, and its title and docstring are the only text any view shows for it."""

    keys: ClassVar[Mapping[type[EditingMode], tuple[str, ...]]] = MappingProxyType({})
    show: ClassVar[bool] = False
    priority: ClassVar[bool] = False
    group: ClassVar[Binding.Group | None] = None
    key_display: ClassVar[str | None] = None
    binding_prefix: ClassVar[str] = ""

    @classmethod
    def default_title(cls) -> str:
        return cls.declared_name.replace("_", " ").capitalize()

    @classmethod
    def declarations(cls):
        """Each nested family retains its own declaration registry."""
        pending = [cls]
        families = set()
        while pending:
            declaration = pending.pop()
            pending.extend(declaration.__subclasses__())
            family = declaration.family_root
            if family not in families:
                families.add(family)
                yield from family.members_with(cls)

    @classmethod
    def summary(cls) -> str:
        """The nearest docstring a member declares; the family roots document code, not keys."""
        root = cls.family_root
        return next((inspect.cleandoc(base.__doc__) for base in cls.__mro__
                     if issubclass(base, root) and base is not root and base.__doc__), "")

    @classmethod
    def binding_name(cls) -> str:
        return cls.binding_prefix + cls.declared_name

    @classmethod
    def bindings(cls) -> tuple[Binding, ...]:
        return tuple(cls.mode_binding(mode, key)
                     for mode, keys in cls.keys.items() for key in keys)

    @classmethod
    def mode_binding(cls, mode: type[EditingMode], key: str) -> ModeBinding:
        command = cls.command_for_key(mode, key)
        return cls.command_binding(mode, key, command, mode)

    @classmethod
    def command_binding(cls, capability: type[EditingMode], key: str, command: Self,
                        mode: type[EditingMode]) -> ModeBinding:
        return CommandBinding(
            key=key, action=command, description=cls.title,
            available=command.key_available, mode=capability,
            tooltip=cls.summary(), show=cls.show, priority=cls.priority,
            system=cls.system, group=cls.group, key_display=cls.key_display,
            id=command.binding_identity(mode),
        )

    @classmethod
    def bindings_for(cls, mode: type[EditingMode]) -> tuple[Binding, ...]:
        """The nearest declared capability supplies defaults; identity follows active mode."""
        for capability in mode.__mro__:
            if capability in cls.keys:
                return tuple(cls.command_binding(capability, key,
                                                 cls.command_for_key(capability, key), mode)
                             for key in cls.keys[capability])
        return ()

    @classmethod
    def command_for_key(cls, mode: type[EditingMode], key: str) -> Self:
        return cls()

    def __call__(self, context: Context) -> object:
        return self.apply(context)

    @classmethod
    def configured_bindings(cls, context: Context) -> tuple[Binding, ...]:
        """Declared keys after remapping, also when this control is not focused."""
        mode = context.screen.active_binding_mode
        identities = {binding.id for binding in cls.bindings_for(mode)}
        bindings = context.binding_map(mode)
        bindings.apply_keymap(context.app._keymap)
        return tuple(binding for _, binding in bindings if binding.id in identities
                     and binding.state(context.app, context))

    @classmethod
    def active_bindings(cls, context: Context) -> tuple[Binding, ...]:
        identities = {binding.id for binding in cls.bindings_for(context.screen.active_binding_mode)}
        return tuple(binding for node, bindings in context.screen._binding_chain if node is context
                     for _, binding in bindings if binding.id in identities
                     and binding.state(context.app, context))

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

    def key_available(self, context: Context) -> bool | None:
        """Keyboard scope may be narrower than menu/palette command availability."""
        return self.available(context)

    @abstractmethod
    def apply(self, context: Context) -> object: ...


class System:
    """Only its key reaches the action: no menu, palette or key panel shows it."""

    system: ClassVar[bool] = True

    @classmethod
    def offered(cls, context) -> Iterator[Action]:
        return iter(())


class YieldingKey:
    """An application key that any binding closer to the focus replaces: it answers only
    where nothing local claims the key, so the claim is no conflict."""

    @classmethod
    def exclusive_bindings(cls, mode: type[EditingMode]) -> tuple[Binding, ...]:
        return ()


class ExclusiveKeys:
    """One declared family of mutually exclusive actions may share its default keys."""

    @classmethod
    def permits_key_overlap(cls, other: type[KeyDeclaration]) -> bool:
        family = next(base for base in cls.__mro__ if ExclusiveKeys in base.__bases__)
        return issubclass(other, family)


class ApplicationAction(Action, affix="Action"):
    binding_prefix = "app."

    @classmethod
    def exclusive_bindings(cls, mode: type[EditingMode]) -> tuple[Binding, ...]:
        return cls.bindings_for(mode)

    @classmethod
    def menu(cls, app):
        """Every offered member under its label, in declaration order."""
        return tuple((command, command.label(app))
                     for member in cls.members_with(cls) for command in member.offered(app))


class VimWorkspaceAction(ApplicationAction, declared_name=None):
    """Workspace commands precede editor bindings only in idle modal command entry."""

    priority = True

    def key_available(self, app):
        return (app.screen is app.workspace_screen
                and app.screen.allows_application_commands)


class DeclaredWidgetActions(ToadNode):
    """One family supplies both native dispatch and dynamic availability."""

    own_actions: ClassVar[tuple[type[Action], ...]] = ()

    @classmethod
    def contexts(cls) -> tuple[type[DeclaredWidgetActions], ...]:
        pending = [cls]
        found: dict[type[DeclaredWidgetActions], None] = {}
        while pending:
            owner = pending.pop()
            if owner not in found:
                found[owner] = None
                pending.extend(reversed(owner.__subclasses__()))
        return tuple(found)

    @classmethod
    def declared_actions(cls) -> tuple[type[Action], ...]:
        """Capabilities and the widget's own family compose through its MRO."""
        return tuple(dict.fromkeys(
            member for base in cls.__mro__
            for family in base.__dict__.get("own_actions", ())
            for member in family.members_with(family)
        ))

    @classmethod
    def action_bindings(cls, declaration: type[Action], mode: type[EditingMode]) -> tuple[Binding, ...]:
        return declaration.bindings_for(mode)

    @classmethod
    def native_bindings(cls, mode: type[EditingMode]) -> tuple[ModeBinding, ...]:
        return ()

    @classmethod
    def declared_bindings(cls, mode: type[EditingMode]) -> tuple[Binding, ...]:
        return (*cls.native_bindings(mode),
                *(binding for declaration in cls.declared_actions()
                  for binding in cls.action_bindings(declaration, mode)))

    def binding_map(self, mode: type[EditingMode]) -> BindingsMap:
        return BindingsMap.merge((super().binding_map(mode),
                                  BindingsMap(self.declared_bindings(mode))))

    def __init_subclass__(cls, actions: tuple[type[Action], ...] = (), **kwargs):
        cls.own_actions = actions
        declarations = cls.declared_actions()
        for declaration in declarations:
            dispatch = (cls._run_declared_async_action if inspect.iscoroutinefunction(declaration.apply)
                        else cls._run_declared_action)
            setattr(cls, f"action_{declaration.declared_name}", partialmethod(dispatch, declaration))
        super().__init_subclass__(**kwargs)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        for declaration in self.declared_actions():
            if action == declaration.declared_name:
                return declaration.parse(parameters).key_available(self)
        return super().check_action(action, parameters)

    def _run_declared_action(self, declaration, *parameters) -> object:
        command = declaration.parse(parameters)
        if command.available(self):
            return command.apply(self)
        return None

    async def _run_declared_async_action(self, declaration, *parameters) -> None:
        await invoke(self._run_declared_action, declaration, *parameters)


class NativeMethodKeys(DeclaredWidgetActions):
    """Project native callable declarations without another action implementation."""

    @classmethod
    def method_key_owners(cls) -> tuple[type, ...]:
        return cls.__mro__

    @classmethod
    def native_bindings(cls, mode: type[EditingMode]) -> tuple[ModeBinding, ...]:
        return tuple(projected for base in cls.method_key_owners()
                     for binding in base.__dict__.get("MODE_BINDINGS", ())
                     for projected in binding.for_mode(mode))


class LocalMethodKeys(NativeMethodKeys):
    """Local editor effects exclude scrolling keys from foreign widget bases.

    Subclasses retain their local parents' declarations. The native editor owns
    its editing commands; generic Widget scrolling is a different key scope.
    """

    @classmethod
    def method_key_owners(cls) -> tuple[type, ...]:
        return cls.__mro__[:cls.__mro__.index(LocalMethodKeys)]


class ProfileKeys(NativeMethodKeys):
    """Workspace and modal scopes borrow the canonical preference, never mirror it."""

    @property
    def key_mode(self) -> type[EditingMode]:
        return self.app.settings.ui.key_mode


class WidgetAction(Action, affix="Action"):
    """Keyboard operations on the focused widget, distinct from configured commands."""


class VisibleAction(WidgetAction):
    show = True


class DismissAction(VisibleAction):
    """Close the current control."""
    keys = {EditingMode: ("escape",)}

    async def apply(self, context: DismissibleControl) -> None:
        context.dismiss_control()


class CursorAction(VisibleAction, affix="Action"):
    group = Binding.Group("Select")


class CursorUpAction(CursorAction):
    keys = {EditingMode: ("up",)}

    async def apply(self, context: MovesCursor) -> None:
        context.cursor_up()


class CursorDownAction(CursorAction):
    keys = {EditingMode: ("down",)}

    async def apply(self, context: MovesCursor) -> None:
        context.cursor_down()


class HorizontalCursorAction(CursorAction, declared_name=None):
    direction: ClassVar[Literal[-1, 1]]

    async def apply(self, context: MovesHorizontalCursor) -> None:
        context.cursor_horizontal(self.direction)


class CursorLeftAction(HorizontalCursorAction):
    keys = {EditingMode: ("left",)}
    direction = -1


class CursorRightAction(HorizontalCursorAction):
    keys = {EditingMode: ("right",)}
    direction = +1


class SubmitAction(VisibleAction):
    keys = {EditingMode: ("enter",)}

    async def apply(self, context: Submits) -> None:
        context.submit()


class SelectAction(VisibleAction):
    keys = {EditingMode: ("enter",)}

    async def apply(self, context: Selects) -> None:
        context.select()


class OpenSelectedAction(VisibleAction):
    title = "Open"
    keys = {EditingMode: ("enter",)}

    async def apply(self, context: OpensSelected) -> None:
        context.open_selected()


class LaunchAction(VisibleAction):
    keys = {EditingMode: ("space",)}

    async def apply(self, context: Launches) -> None:
        await context.launch()


class ActivateAction(WidgetAction):
    keys = {EditingMode: ("enter", "space")}

    async def apply(self, context: ActivationKeys) -> None:
        await invoke(context.primary_activation)


class ToggleIrcAction(VisibleAction):
    title = "IRC view"
    keys = {EditingMode: ("ctrl+g",)}

    async def apply(self, context: TogglesIrc) -> None:
        await context.toggle_irc()


SESSION_NAVIGATION_GROUP = Binding.Group(description="Sessions")


class SessionNavigationAction(VisibleAction, affix="Action"):
    group = SESSION_NAVIGATION_GROUP
    direction: ClassVar[Literal[-1, 1]]

    async def apply(self, context: CyclesSessions) -> None:
        context.navigate_session(self.direction)


class SessionPreviousAction(SessionNavigationAction):
    keys = {EditingMode: ("ctrl+left_square_bracket",)}
    direction = -1


class SessionNextAction(SessionNavigationAction):
    keys = {EditingMode: ("ctrl+right_square_bracket",)}
    direction = +1


class FocusAction(VisibleAction, affix="Action"):
    group = Binding.Group("Focus")


class FocusNextAction(FocusAction):
    keys = {EditingMode: ("tab",)}

    async def apply(self, context: CyclesFocus) -> None:
        context.app.action_focus_next()


class FocusPreviousAction(FocusAction):
    keys = {EditingMode: ("shift+tab",)}

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


class MovesHorizontalCursor(DeclaredWidgetActions, actions=(HorizontalCursorAction,)):
    @abstractmethod
    def cursor_horizontal(self, direction: Literal[-1, 1]) -> None: ...


class Submits(DeclaredWidgetActions, actions=(SubmitAction,)):

    @abstractmethod
    def submit(self) -> None: ...


class Selects(DeclaredWidgetActions, actions=(SelectAction,)):

    @abstractmethod
    def select(self) -> None: ...


class OpensSelected(DeclaredWidgetActions, actions=(OpenSelectedAction,)):

    @abstractmethod
    def open_selected(self) -> None: ...


class Launches(DeclaredWidgetActions, actions=(LaunchAction,)):

    @abstractmethod
    async def launch(self) -> None: ...


class ActivationKeys(PrimaryActivation, DeclaredWidgetActions, actions=(ActivateAction,)):
    """Keys and primary clicks use the native activation callback, including async effects."""

    activation_buttons: ClassVar[tuple[int, ...]] = (1,)

    async def on_click(self, event: events.Click) -> None:
        if event.button in self.activation_buttons:
            event.stop()
            await invoke(self.primary_activation)


class Activates(ActivationKeys):
    """A control whose primary effect is its own activate method."""

    @property
    def primary_activation(self):
        return self.activate

    @abstractmethod
    def activate(self) -> object: ...


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
    def action_bindings(cls, declaration: type[Action], mode: type[EditingMode]) -> tuple[Binding, ...]:
        return tuple(cls.present_binding(declaration, binding)
                     for binding in super().action_bindings(declaration, mode))


class PriorityActions(ActionPresentation,
                      fields=(FieldCodec.field_plan(Binding, "priority"),), combine=or_):
    """The selected actions take precedence over focused controls."""


class HiddenActions(ActionPresentation,
                    fields=(FieldCodec.field_plan(Binding, "show"),), combine=hide):
    """The selected actions stay out of the footer."""


class VisibleActions(ActionPresentation,
                     fields=(FieldCodec.field_plan(Binding, "show"),), combine=or_):
    """The selected actions are offered in the footer."""
