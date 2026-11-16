"""Textual's actions on widgets, and the Textual projection of every declared action's keys."""
from __future__ import annotations

import inspect
from abc import abstractmethod
from collections.abc import Callable, Mapping
from copy import replace
from dataclasses import dataclass
from functools import lru_cache, partialmethod
from operator import or_
from types import MappingProxyType
from typing import ClassVar, Literal, TypeVar

from agent_comms.nominal.field_codec import FieldCodec, FieldPlan
from formbridge.key_declarations import DeclaredKey, InputMode, KeyDeclaration, KeyDeclarationType, TextEntryMode, UndecodedKey
from textual import events, on
from textual._activation import PrimaryActivation
from textual._callback import invoke
from textual.binding import Binding, BindingsMap, CommandBinding, ModeBinding
from textual.document._editing import VimMode
from textual.dom import DOMNode
from formbridge.hint_keys import HintLabelStyle
from formbridge.navigation_commands import SelectCursor
from textual.navigation import MovesCursor, MovesHorizontalCursor
from textual.widgets import TextArea
from textual.widgets._hints import HintClick, HintHost
from textual.widgets.text_area import EditingMode

from toad.app_node import ToadNode
from toad.client.application_actions import ApplicationAction, DeclaredAction, ReplacesFrameworkAction


Context = TypeVar("Context", bound=DOMNode)


class EngineKey(DeclaredKey):
    """A key an external editing engine receives first and offers back at its own boundary.

    The engine maps the key to itself: declining the boundary leaves the key's native meaning.
    """

    def input_bindings(self, spelling: str) -> tuple[tuple[str, str], ...]:
        return ((spelling, spelling),)


@dataclass(frozen=True, kw_only=True)
class ActionBinding(CommandBinding):
    """An action's binding; an engine boundary for its key is the action's to answer."""

    def engine_boundary(self, editor: TextArea) -> bool:
        return self.action.engine_boundary(editor)


class Action(DeclaredAction[Context], affix="Action"):
    """An action on a Textual widget: its key may join a footer group and an engine's input."""

    group: ClassVar[Binding.Group | None] = None
    declared_key: ClassVar[DeclaredKey] = UndecodedKey()

    @classmethod
    def refine_binding(cls, binding: ActionBinding) -> ActionBinding:
        return replace(binding, group=cls.group, declared_key=cls.declared_key)


class ExclusiveKeys:
    """One declared family of mutually exclusive actions may share its default keys."""

    @classmethod
    def permits_key_overlap(cls, other: KeyDeclarationType) -> bool:
        family = next(base for base in cls.__mro__ if ExclusiveKeys in base.__bases__)
        return issubclass(other, family)


class VimWorkspaceAction(ApplicationAction, declared_name=None):
    """Workspace commands precede editor bindings only in idle modal command entry."""

    def key_available(self, app) -> bool:
        if app.current_mode != "workspace":
            return False
        return (app.screen is app.workspace_screen
                and app.screen.allows_application_commands)


class DeclaredWidgetActions(ToadNode):
    """One family supplies both native dispatch and dynamic availability."""

    own_actions: ClassVar[tuple[type[DeclaredAction], ...]] = ()

    @classmethod
    def declared_actions(cls) -> tuple[type[DeclaredAction], ...]:
        """Capabilities and the widget's own family compose through its MRO."""
        return tuple(dict.fromkeys(
            member for family in cls.declared_items("own_actions")
            for member in family.members_with(family)
        ))

    @staticmethod
    def key_bindings(declaration: type[DeclaredAction]) -> tuple[Binding, ...]:
        """A declaration's default bindings in every mode it declares keys for."""
        return tuple(DeclaredWidgetActions.command_binding(
                         declaration, mode, key, declaration.command_for_key(mode, key))
                     for mode, keys in declaration.keys.items() for key in keys)

    @staticmethod
    def command_binding(declaration: type[DeclaredAction], capability: type[InputMode], key: str,
                        command: DeclaredAction) -> ModeBinding:
        return declaration.refine_binding(ActionBinding(
            key=key, action=command, description=declaration.title,
            available=command.key_available, mode=capability,
            tooltip=declaration.summary(), show=declaration.show, priority=declaration.priority,
            system=declaration.system, key_display=declaration.key_display,
        ))

    @staticmethod
    def mode_bindings(declaration: type[DeclaredAction], mode: type[TextEntryMode]) -> tuple[Binding, ...]:
        """The nearest declared capability supplies defaults; identity follows active mode."""
        for capability in mode.__mro__:
            if capability in declaration.keys:
                return tuple(binding for _, binding in BindingsMap(
                    DeclaredWidgetActions.command_binding(
                        declaration, capability, key, declaration.command_for_key(capability, key))
                    for key in declaration.keys[capability]
                ).project(mode))
        return ()

    @staticmethod
    def exclusive_bindings(declaration: type[DeclaredAction], mode: type[TextEntryMode]) -> tuple[Binding, ...]:
        return declaration.exclusive_claims(DeclaredWidgetActions.mode_bindings(declaration, mode))

    def configured_bindings(self, declaration: type[DeclaredAction]) -> tuple[Binding, ...]:
        """Declared keys after remapping, also when this control is not focused."""
        mode = self.binding_mode
        identities = {binding.id for binding in self.mode_bindings(declaration, mode)}
        bindings = self.binding_map(mode)
        bindings.apply_keymap(self.app._keymap)
        return tuple(binding for _, binding in bindings if binding.id in identities
                     and binding.state(self.app, self))

    def active_declared_bindings(self, declaration: type[DeclaredAction]) -> tuple[Binding, ...]:
        identities = {binding.id for binding in self.mode_bindings(declaration, self.binding_mode)}
        return tuple(binding for node, bindings in self.screen._binding_chain if node is self
                     for _, binding in bindings if binding.id in identities
                     and binding.state(self.app, self))

    @classmethod
    def declaration_bindings(cls, declaration: type[DeclaredAction], mode: type[TextEntryMode]) -> tuple[Binding, ...]:
        return cls.mode_bindings(declaration, mode)

    @classmethod
    def declared_bindings(cls, mode: type[TextEntryMode]) -> tuple[Binding, ...]:
        return (*super().declared_bindings(mode),
                *(binding for declaration in cls.declared_actions()
                  for binding in cls.declaration_bindings(declaration, mode)))

    @classmethod
    @lru_cache(maxsize=None)
    def _scope_bindings(cls, mode: type[TextEntryMode]) -> tuple[Binding, ...]:
        """What this class answers as a keyboard scope outside the focus chain: each declared binding's
        fallbacks. Immutable and per (class, mode), like Textual's own `_binding_defaults`."""
        return tuple(scoped for binding in cls.declared_bindings(mode) for scoped in binding.fallback_bindings())

    def scope_bindings(self) -> BindingsMap:
        """A fresh map over this scope's frozen bindings for the current mode."""
        return BindingsMap(self._scope_bindings(self.binding_mode))

    def __init_subclass__(cls, actions: tuple[type[DeclaredAction], ...] = (), **kwargs):
        cls.own_actions = actions
        declarations = cls.declared_actions()
        for declaration in declarations:
            name = f"action_{declaration.declared_name}"
            declaration.require_unwritten(name, tuple(
                base for base in cls.__mro__
                if name in base.__dict__ and not isinstance(base.__dict__[name], partialmethod)))
            dispatch = (cls._run_declared_async_action if inspect.iscoroutinefunction(declaration.apply)
                        else cls._run_declared_action)
            setattr(cls, name, partialmethod(dispatch, declaration))
        super().__init_subclass__(**kwargs)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        for declaration in self.declared_actions():
            if action == declaration.declared_name:
                return declaration.parse(parameters).key_available(self)
        return super().check_action(action, parameters)

    def _run_declared_action(self, declaration: type[DeclaredAction], *parameters: object) -> object:
        command = declaration.parse(parameters)
        if command.available(self):
            return command.apply(self)
        return None

    async def _run_declared_async_action(self, declaration: type[DeclaredAction], *parameters: object) -> None:
        await invoke(self._run_declared_action, declaration, *parameters)


class NativeMethodKeys(DeclaredWidgetActions):
    """Project native callable declarations without another action implementation."""

    @classmethod
    def method_key_owners(cls) -> tuple[type, ...]:
        return cls.__mro__


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

    @property
    def hint_label_style(self) -> type[HintLabelStyle]:
        return self.app.settings.ui.hint_labels


class HintKeys(ProfileKeys):
    """In a Vim profile, f and ctrl+f show the screen's left- and right-click hints."""

    MODE_BINDINGS: ClassVar[tuple[ModeBinding, ...]] = (
        ModeBinding("f", HintHost.action_show_hints, HintClick.LEFT.description,
                    mode=VimMode, show=False),
        ModeBinding("ctrl+f", HintHost.action_show_context_hints, HintClick.RIGHT.description,
                    mode=VimMode, show=False),
    )


class WidgetAction(Action, affix="Action"):
    """Keyboard operations on the focused widget, distinct from configured commands."""


class VisibleAction(WidgetAction):
    show = True


class DismissAction(ReplacesFrameworkAction, VisibleAction):
    """Close the current control."""
    keys = {TextEntryMode: ("escape",)}

    async def apply(self, context: DismissibleControl) -> None:
        context.dismiss_control()


class SubmitAction(VisibleAction):
    keys = {TextEntryMode: ("enter",)}

    async def apply(self, context: Submits) -> None:
        context.submit()


class SelectAction(VisibleAction):
    keys = {TextEntryMode: ("enter",)}

    async def apply(self, context: Selects) -> None:
        context.select()


class OpenSelectedAction(VisibleAction):
    title = "Open"
    keys = {TextEntryMode: ("enter",)}

    @classmethod
    def permits_key_overlap(cls, other: KeyDeclarationType) -> bool:
        """Opening the row is what selecting the cursor means on a list that opens rows."""
        return issubclass(other, SelectCursor)

    async def apply(self, context: OpensSelected) -> None:
        context.open_selected()


class ActivateAction(WidgetAction):
    keys = {TextEntryMode: ("enter", "space")}

    async def apply(self, context: ActivationKeys) -> None:
        await invoke(context.primary_activation)


class ToggleIrcAction(VisibleAction):
    title = "IRC view"
    keys = {TextEntryMode: ("ctrl+g",)}

    async def apply(self, context: TogglesIrc) -> None:
        await context.toggle_irc()


SESSION_NAVIGATION_GROUP = Binding.Group(description="Sessions")


class SessionNavigationAction(VisibleAction, affix="Action"):
    group = SESSION_NAVIGATION_GROUP
    direction: ClassVar[Literal[-1, 1]]

    async def apply(self, context: CyclesSessions) -> None:
        context.navigate_session(self.direction)


class SessionPreviousAction(SessionNavigationAction):
    keys = {TextEntryMode: ("ctrl+left_square_bracket",)}
    direction = -1


class SessionNextAction(SessionNavigationAction):
    keys = {TextEntryMode: ("ctrl+right_square_bracket",)}
    direction = +1


class FocusAction(VisibleAction, affix="Action"):
    group = Binding.Group("Focus")


class FocusNextAction(FocusAction):
    keys = {TextEntryMode: ("tab",)}

    async def apply(self, context: CyclesFocus) -> None:
        context.app.action_focus_next()


class FocusPreviousAction(FocusAction):
    keys = {TextEntryMode: ("shift+tab",)}

    async def apply(self, context: CyclesFocus) -> None:
        context.app.action_focus_previous()


class Dismisses(DeclaredWidgetActions, actions=(DismissAction,)):
    """The shared Escape binding."""


class DismissibleControl(Dismisses):
    @abstractmethod
    def dismiss_control(self) -> None:
        """Close this control without imposing a native screen result contract."""


class StepsHorizontalCursor(MovesHorizontalCursor):
    """Left and Right step the horizontal cursor by -1 and +1; the widget says what a step is."""

    @abstractmethod
    def step_horizontal(self, direction: Literal[-1, 1]) -> None: ...

    def action_cursor_left(self) -> None:
        self.step_horizontal(-1)

    def action_cursor_right(self) -> None:
        self.step_horizontal(+1)


class StepsVerticalCursor(MovesCursor):
    """Up and Down step the vertical cursor by -1 and +1; the widget says what a step is."""

    @abstractmethod
    def step_vertical(self, direction: Literal[-1, 1]) -> None: ...

    def action_cursor_up(self) -> None:
        self.step_vertical(-1)

    def action_cursor_down(self) -> None:
        self.step_vertical(+1)


class ForwardsCursor(MovesCursor):
    """Up and Down move the cursor of the child list that holds it; the widget names that child."""

    @property
    @abstractmethod
    def cursor_owner(self) -> MovesCursor: ...

    def action_cursor_up(self) -> None:
        self.cursor_owner.action_cursor_up()

    def action_cursor_down(self) -> None:
        self.cursor_owner.action_cursor_down()


class Submits(DeclaredWidgetActions, actions=(SubmitAction,)):

    @abstractmethod
    def submit(self) -> None: ...


class Selects(DeclaredWidgetActions, actions=(SelectAction,)):

    @abstractmethod
    def select(self) -> None: ...


class OpensSelected(DeclaredWidgetActions, actions=(OpenSelectedAction,)):

    @abstractmethod
    def open_selected(self) -> None: ...


class ActivationKeys(PrimaryActivation, DeclaredWidgetActions, actions=(ActivateAction,)):
    """Keys and primary clicks use the native activation callback, including async effects."""

    activation_buttons: ClassVar[tuple[int, ...]] = (1,)

    @on(events.Click)
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
PresentationScopes = Mapping[type, tuple[type[KeyDeclaration], ...]]


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
        actions: tuple[type[DeclaredAction], ...] = (), **kwargs: object,
    ) -> None:
        cls.binding_styles = tuple(BindingStyle(field, combine) for field in fields)
        cls.scopes = scopes
        super().__init_subclass__(actions=actions, **kwargs)

    @classmethod
    def present_binding(cls, declaration: type[KeyDeclaration], binding: Binding) -> Binding:
        scopes = {family: members
                  for _, declared in cls.own_declarations("scopes", reversed(cls.__mro__))
                  for family, members in declared.items()}
        for base, styles in cls.own_declarations("binding_styles", reversed(cls.__mro__)):
            for style in styles:
                selected = any(root in declaration.__mro__ for root in scopes.get(base, (KeyDeclaration,)))
                binding = replace(binding, **{
                    style.field.name: style.combine(bool(style.field.current(binding)), selected)
                })
        return binding

    @classmethod
    def declaration_bindings(cls, declaration: type[DeclaredAction], mode: type[TextEntryMode]) -> tuple[Binding, ...]:
        return tuple(cls.present_binding(declaration, binding)
                     for binding in super().declaration_bindings(declaration, mode))


class PriorityActions(ActionPresentation,
                      fields=(FieldCodec.field_plan(Binding, "priority"),), combine=or_):
    """The selected actions take precedence over focused controls."""


class HiddenActions(ActionPresentation,
                    fields=(FieldCodec.field_plan(Binding, "show"),), combine=hide):
    """The selected actions stay out of the footer."""


class VisibleActions(ActionPresentation,
                     fields=(FieldCodec.field_plan(Binding, "show"),), combine=or_):
    """The selected actions are offered in the footer."""
