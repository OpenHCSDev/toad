"""

This module contains the `Screen` class and related objects.

The `Screen` class is a special widget which represents the content in the terminal. See [Screens](/guide/screens/) for details.

"""

from __future__ import annotations

import asyncio
from contextlib import AbstractContextManager, ExitStack, nullcontext
from functools import partial
from operator import attrgetter
from typing import (
    TYPE_CHECKING,
    Any,
    Awaitable,
    Callable,
    ClassVar,
    Generic,
    Iterable,
    Iterator,
    Literal,
    NamedTuple,
    Optional,
    TypeVar,
    Union,
)

import rich.repr
from rich.console import RenderableType
from rich.style import Style

from textual import constants, errors, events, messages
from textual._arrange import arrange
from textual._auto_scroll import get_auto_scroll_regions
from textual._callback import invoke
from textual._compositor import Compositor, MapGeometry
from textual._context import active_message_pump, visible_screen_stack
from textual._path import (
    CSSPathType,
    _css_path_type_as_list,
    _make_path_object_relative,
)
from textual._types import CallbackType
from textual.actions import SkipAction
from textual.await_complete import AwaitComplete
from textual.binding import ActiveBinding, Binding, BindingsMap
from textual.css.match import match
from textual.css.parse import parse_selectors
from textual.css.query import NoMatches, QueryType
from textual.css.styles import PointerShape
from textual.dom import DOMNode
from textual.errors import NoWidget
from textual.geometry import Offset, Region, Size
from textual.keys import key_to_character
from textual.layout import DockArrangeResult
from textual.message_pump import MessagePump, MessagePumpClosed
from textual.reactive import Reactive, var
from textual.renderables.background_screen import BackgroundScreen
from textual.renderables.blank import Blank
from textual.selection import SELECT_ALL, SelectEnd, Selection, SelectStart, SelectState
from textual.signal import Signal
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Tooltip
from textual.widgets._toast import ToastRack

if TYPE_CHECKING:
    from textual.command import Provider

    # Unused & ignored imports are needed for the docs to link to these objects:
    from textual.message_pump import MessagePump

ScreenResultType = TypeVar("ScreenResultType")
"""The result type of a screen."""

ScreenResultCallbackType = Union[
    Callable[[Optional[ScreenResultType]], None],
    Callable[[Optional[ScreenResultType]], Awaitable[None]],
]
"""Type of a screen result callback function."""


class HoverWidgets(NamedTuple):
    """Result of [get_hover_widget_at][textual.screen.Screen.get_hover_widget_at]"""

    mouse_over: tuple[Widget, Region]
    """Widget and region directly under the mouse."""
    hover_over: tuple[Widget, Region] | None
    """Widget with a hover style under the mouse, or `None` for no hover style widget."""

    @property
    def widgets(self) -> tuple[Widget, Widget | None]:
        """Just the widgets."""
        return (
            self.mouse_over[0],
            None if self.hover_over is None else self.hover_over[0],
        )


@rich.repr.auto
class ResultCallback(Generic[ScreenResultType]):
    """Holds the details of a callback."""

    def __init__(
        self,
        requester: MessagePump,
        callback: ScreenResultCallbackType[ScreenResultType] | None,
        future: asyncio.Future[ScreenResultType] | None = None,
    ) -> None:
        """Initialise the result callback object.

        Args:
            requester: The object making a request for the callback.
            callback: The callback function.
            future: A Future to hold the result.
        """
        self.requester = requester
        """The object in the DOM that requested the callback."""
        self.callback: ScreenResultCallbackType | None = callback
        """The callback function."""
        self.future = future
        """A future for the result"""

    def __call__(self, result: ScreenResultType) -> None:
        """Call the callback, passing the given result.

        Args:
            result: The result to pass to the callback.

        Note:
            If the requested or the callback are `None` this will be a no-op.
        """
        if self.future is not None:
            self.future.set_result(result)
        if self.requester is not None and self.callback is not None:
            self.requester.call_next(self.callback, result)
        self.callback = None


@rich.repr.auto
class Screen(Generic[ScreenResultType], Widget):
    """The base class for screens."""

    AUTO_FOCUS: ClassVar[str | None] = None
    """A selector to determine what to focus automatically when the screen is activated.

    The widget focused is the first that matches the given [CSS selector](/guide/queries/#query-selectors).
    Set to `None` to inherit the value from the screen's app.
    Set to `""` to disable auto focus.
    """

    CSS: ClassVar[str] = ""
    """Inline CSS, useful for quick scripts. Rules here take priority over CSS_PATH.

    Note:
        This CSS applies to the whole app.
    """
    CSS_PATH: ClassVar[CSSPathType | None] = None
    """File paths to load CSS from.

    Note:
        This CSS applies to the whole app.
    """

    COMPONENT_CLASSES = {"screen--selection"}

    DEFAULT_CSS = """
    Screen {
        layout: vertical;
        overflow-y: auto;
        background: $background;        
        
        &:inline {
            height: auto;
            min-height: 1;
            border-top: tall $background;
            border-bottom: tall $background;
        }
        & > .screen--selection {
            background: $screen-selection-background;
            color: $screen-selection-foreground;           
        }
        &:ansi {
            background: ansi_default;
            color: ansi_default;
            &.-screen-suspended {
                text-style: dim;
                ScrollBar {
                    text-style: not dim;
                }
            }
            &:inline {
                border-top: tall $ansi-background;
                border-bottom: tall $ansi-background;
            }
        }
    }
    
    """

    TITLE: ClassVar[str | None] = None
    """A class variable to set the *default* title for the screen.

    This overrides the app title.
    To update the title while the screen is running,
    you can set the [title][textual.screen.Screen.title] attribute.
    """

    SUB_TITLE: ClassVar[str | None] = None
    """A class variable to set the *default* sub-title for the screen.

    This overrides the app sub-title.
    To update the sub-title while the screen is running,
    you can set the [sub_title][textual.screen.Screen.sub_title] attribute.
    """

    HORIZONTAL_BREAKPOINTS: ClassVar[list[tuple[int, str]]] | None = None
    """Horizontal breakpoints, will override [App.HORIZONTAL_BREAKPOINTS][textual.app.App.HORIZONTAL_BREAKPOINTS] if not `None`."""
    VERTICAL_BREAKPOINTS: ClassVar[list[tuple[int, str]]] | None = None
    """Vertical breakpoints, will override [App.VERTICAL_BREAKPOINTS][textual.app.App.VERTICAL_BREAKPOINTS] if not `None`."""

    focused: Reactive[Widget | None] = Reactive(None)
    """The focused [widget][textual.widget.Widget] or `None` for no focus.
    To set focus, do not update this value directly. Use [set_focus][textual.screen.Screen.set_focus] instead."""
    stack_updates: Reactive[int] = Reactive(0, repaint=False)
    """An integer that updates when the screen is resumed."""
    sub_title: Reactive[str | None] = Reactive(None, compute=False)
    """Screen sub-title to override [the app sub-title][textual.app.App.sub_title]."""
    title: Reactive[str | None] = Reactive(None, compute=False)
    """Screen title to override [the app title][textual.app.App.title]."""

    COMMANDS: ClassVar[set[type[Provider] | Callable[[], type[Provider]]]] = set()
    """Command providers used by the [command palette](/guide/command_palette), associated with the screen.

    Should be a set of [`command.Provider`][textual.command.Provider] classes.
    """
    ALLOW_IN_MAXIMIZED_VIEW: ClassVar[str | None] = None
    """A selector for the widgets (direct children of Screen) that are allowed in the maximized view (in addition to maximized widget). Or
    `None` to default to [App.ALLOW_IN_MAXIMIZED_VIEW][textual.app.App.ALLOW_IN_MAXIMIZED_VIEW]"""

    ESCAPE_TO_MINIMIZE: ClassVar[bool | None] = None
    """Use escape key to minimize (potentially overriding bindings) or `None` to defer to [`App.ESCAPE_TO_MINIMIZE`][textual.app.App.ESCAPE_TO_MINIMIZE]."""

    maximized: Reactive[Widget | None] = Reactive(None, layout=True)
    """The currently maximized widget, or `None` for no maximized widget."""

    selections: var[dict[Widget, Selection]] = var(dict)
    """Map of widgets and selected ranges."""

    # Selection paints through the changed widgets' own refreshes. Repainting
    # the entire screen whenever the pointer moves makes transcript drags
    # scale with every mounted history pane and forces a full compositor pass.
    _select_state: Reactive[SelectState | None] = Reactive(None, repaint=False)
    """Pointer range, retained after release for selection projection and copy."""

    _mouse_down_offset: var[Offset | None] = var(None)
    """Primary press screen offset, or `None` after its release."""

    _pointer_shape: var[PointerShape] = var("default")
    """The current mouse pointer shape."""

    BINDINGS = [
        Binding("tab", "app.focus_next", "Focus Next", show=False),
        Binding("shift+tab", "app.focus_previous", "Focus Previous", show=False),
        Binding("ctrl+c,super+c", "screen.copy_text", "Copy selected text", show=False),
    ]

    def __init__(
        self,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """
        Initialize the screen.

        Args:
            name: The name of the screen.
            id: The ID of the screen in the DOM.
            classes: The CSS classes for the screen.
        """
        self._modal = False
        super().__init__(name=name, id=id, classes=classes)
        self._compositor = Compositor(max_subtree_geometry_entries=self.SUBTREE_GEOMETRY_CACHE_ENTRIES)
        self._dirty_widgets: set[Widget] = set()
        self._selection_update_pending = False
        self.__update_timer: Timer | None = None
        self._callbacks: list[tuple[CallbackType, MessagePump]] = []
        self._result_callbacks: list[ResultCallback[ScreenResultType | None]] = []

        self._tooltip_widget: Widget | None = None
        self._tooltip_timer: Timer | None = None

        css_paths = [
            _make_path_object_relative(css_path, self)
            for css_path in (
                _css_path_type_as_list(self.CSS_PATH)
                if self.CSS_PATH is not None
                else []
            )
        ]
        self.css_path = css_paths

        self.title = self.TITLE
        self.sub_title = self.SUB_TITLE

        self.screen_layout_refresh_signal: Signal[Screen] = Signal(
            self, "layout-refresh"
        )
        """The signal that is published when the screen's layout is refreshed."""

        self.bindings_updated_signal: Signal[Screen] = Signal(self, "bindings_updated")
        """A signal published when the bindings have been updated"""

        self.text_selection_started_signal: Signal[Screen] = Signal(
            self, "selection_started"
        )
        """A signal published when text selection has started."""

        self._css_update_count = -1
        """Track updates to CSS."""

        self._layout_widgets: dict[DOMNode, set[Widget]] = {}
        """Widgets whose layout may have changed."""

        self._auto_select_scroll_timer: Timer | None = None
        """A timer to auto scroll a container."""

    @property
    def is_modal(self) -> bool:
        """Is the screen modal?"""
        return self._modal

    @property
    def is_current(self) -> bool:
        """Is the screen current (i.e. visible to user)?"""
        from textual.app import ScreenStackError

        try:
            return self.app.screen is self or self in self.app._background_screens
        except ScreenStackError:
            return False

    @property
    def _update_timer(self) -> Timer:
        """Timer used to perform updates."""
        if self.__update_timer is None:
            self.__update_timer = self.set_interval(
                self.app.frame_interval, self._on_timer_update, name="screen_update", pause=True
            )
        return self.__update_timer

    @property
    def layers(self) -> tuple[str, ...]:
        """Layers from parent.

        Returns:
            Tuple of layer names.
        """
        extras = ["_loading"]
        if not self.app._disable_notifications:
            extras.append("_toastrack")
        if not self.app._disable_tooltips:
            extras.append("_tooltips")
        return (*super().layers, *extras)

    @property
    def size(self) -> Size:
        """The size of the screen."""
        return self.app.size - self.styles.gutter.totals

    def _watch_focused(self):
        self.refresh_bindings()

    def _watch_stack_updates(self):
        self.refresh_bindings()

    async def _watch_selections(
        self,
        old_selections: dict[Widget, Selection],
        selections: dict[Widget, Selection],
    ):
        painted = self._compositor.visible_widgets
        for widget in old_selections.keys() | selections.keys():
            previous = old_selections.get(widget)
            current = selections.get(widget)
            if previous != current:
                if widget in painted or type(widget).selection_updated is not Widget.selection_updated:
                    widget.selection_updated(current)
                else:
                    # Dragging across old messages must preserve their full
                    # selection/copy state, but scheduling an off-screen
                    # repaint invalidates the compositor's whole layout map.
                    # Clear only this widget's render caches. Its next exposed
                    # scroll frame will render the current selection then.
                    widget._layout_cache.clear()
                    widget._rich_style_cache.clear()
                    widget._set_dirty()

    def refresh_bindings(self) -> None:
        """Call to request a refresh of bindings."""
        self.bindings_updated_signal.publish(self)

    def _watch_maximized(
        self, previously_maximized: Widget | None, maximized: Widget | None
    ) -> None:
        # The screen gets a `-maximized-view` class if there is a maximized widget
        # The widget gets a `-maximized` class if it is maximized
        self.set_class(maximized is not None, "-maximized-view")
        if previously_maximized is not None:
            previously_maximized.remove_class("-maximized")
        if maximized is not None:
            maximized.add_class("-maximized")

    @property
    def _binding_chain(self) -> list[tuple[DOMNode, BindingsMap]]:
        """Binding chain from this screen."""

        focused = self.focused
        if focused is not None and focused.loading:
            focused = None

        namespace_bindings: list[tuple[DOMNode, BindingsMap]]
        if focused is None:
            namespace_bindings = [
                (self, self._bindings.copy()),
                (self.app, self.app._bindings.copy()),
            ]
        else:
            namespace_bindings = [
                (node, node._bindings.copy()) for node in focused.ancestors_with_self
            ]

        # Filter out bindings that could be captures by widgets (such as Input, TextArea)
        filter_namespaces: list[DOMNode] = []
        for namespace, bindings_map in namespace_bindings:
            for filter_namespace in filter_namespaces:
                check_consume_key = filter_namespace.check_consume_key
                for key in list(bindings_map.key_to_bindings):
                    if check_consume_key(key, key_to_character(key)):
                        # If the widget consumes the key (e.g. like an Input widget),
                        # then remove the key from the bindings map.
                        del bindings_map.key_to_bindings[key]

            filter_namespaces.append(namespace)

        keymap = self.app._keymap
        for namespace, bindings_map in namespace_bindings:
            if keymap:
                result = bindings_map.apply_keymap(keymap)
                if result.clashed_bindings:
                    self.app.handle_bindings_clash(result.clashed_bindings, namespace)

        return namespace_bindings

    @property
    def _modal_binding_chain(self) -> list[tuple[DOMNode, BindingsMap]]:
        """The binding chain, ignoring everything before the last modal."""
        binding_chain = self._binding_chain
        for index, (node, _bindings) in enumerate(binding_chain, 1):
            if node.is_modal:
                return binding_chain[:index]
        return binding_chain

    @property
    def active_bindings(self) -> dict[str, ActiveBinding]:
        """Get currently active bindings for this screen.

        If no widget is focused, then app-level bindings are returned.
        If a widget is focused, then any bindings present in the screen and app are merged and returned.

        This property may be used to inspect current bindings.

        Returns:
            A map of keys to a tuple containing (NAMESPACE, BINDING, ENABLED).
        """
        bindings_map: dict[str, ActiveBinding] = {}
        app = self.app
        for namespace, bindings in self._modal_binding_chain:
            for key, binding in bindings:
                # This will call the nodes `check_action` method.
                action_state = app._check_action_state(binding.action, namespace)
                if action_state is False:
                    # An action_state of False indicates the action is disabled and not shown
                    # Note that None has a different meaning, which is why there is an `is False`
                    # rather than a truthy check.
                    continue

                enabled = bool(action_state)
                if existing_key_and_binding := bindings_map.get(key):
                    # This key has already been bound
                    # Replace priority bindings
                    if (
                        binding.priority
                        and not existing_key_and_binding.binding.priority
                    ):
                        bindings_map[key] = ActiveBinding(
                            namespace, binding, enabled, binding.tooltip
                        )
                else:
                    # New binding
                    bindings_map[key] = ActiveBinding(
                        namespace, binding, enabled, binding.tooltip
                    )

        return bindings_map

    def arrange(self, size: Size, _optimal: bool = False) -> DockArrangeResult:
        """Arrange children.

        Args:
            size: Size of container.
            optimal: Ignored on screen.

        Returns:
            Widget locations.
        """
        # This is customized over the base class to allow for a widget to be maximized
        cache_key = (size, self._nodes._updates, self.maximized)
        cached_result = self._arrangement_cache.get(cache_key)
        if cached_result is not None:
            return cached_result

        allow_in_maximized_view = (
            self.app.ALLOW_IN_MAXIMIZED_VIEW
            if self.ALLOW_IN_MAXIMIZED_VIEW is None
            else self.ALLOW_IN_MAXIMIZED_VIEW
        )

        def get_maximize_widgets(maximized: Widget) -> list[Widget]:
            """Get widgets to display in maximized view.

            Returns:
                A list of widgets.

            """
            # De-duplicate with a set
            widgets = {
                maximized,
                *self.query_children(allow_in_maximized_view),
                *self.query_children(".-textual-system"),
            }
            # Restore order of widgets.
            maximize_widgets = [widget for widget in self.children if widget in widgets]
            # Add the maximized widget, if its not already included
            if maximized not in maximize_widgets:
                maximize_widgets.insert(0, maximized)
            return maximize_widgets

        arrangement = self._arrangement_cache[cache_key] = arrange(
            self,
            (
                get_maximize_widgets(self.maximized)
                if self.maximized is not None
                else self._nodes
            ),
            size,
            self.size,
            False,
        )

        return arrangement

    @property
    def is_active(self) -> bool:
        """Is the screen active (i.e. visible and top of the stack)?"""
        try:
            return self.app.screen is self
        except Exception:
            return False

    @property
    def allow_select(self) -> bool:
        """Check if this widget permits text selection."""
        return self.ALLOW_SELECT

    @property
    def _selecting(self) -> bool:
        """Whether the original primary press still owns a pointer range."""
        return self._mouse_down_offset is not None and self._select_state is not None

    def get_loading_widget(self) -> Widget:
        """Get a widget to display a loading indicator.

        The default implementation will defer to App.get_loading_widget.

        Returns:
            A widget in place of this widget to indicate a loading.
        """
        loading_widget = self.app.get_loading_widget()
        return loading_widget

    def _watch__pointer_shape(self, pointer_shape: PointerShape) -> None:
        self.app._set_pointer_shape(pointer_shape)

    def update_pointer_shape(self) -> None:
        """Get the screen's current pointer shape."""
        if self._selecting:
            self._pointer_shape = "text"
            return
        widget = self if self.app.mouse_over is None else self.app.mouse_over
        pointer_shape = "default"
        for node in widget.walk_ancestors(with_self=True):
            if isinstance(node, Widget):
                if node.loading:
                    pointer_shape = "wait"
                    break
                if (pointer_shape := node.styles.pointer) != "default":
                    break

        self._pointer_shape = pointer_shape

    def render(self) -> RenderableType:
        """Render method inherited from widget, used to render the screen's background.

        Returns:
            Background renderable.
        """
        background = self.styles.background
        try:
            base_screen = visible_screen_stack.get().pop()
        except LookupError:
            base_screen = None

        if base_screen is not None and base_screen is not self and background.a < 1:
            # If background is translucent, render a background screen
            return BackgroundScreen(base_screen, background)

        if background.is_transparent:
            # If the background is transparent, defer to App.render
            return self.app.render()
        # Render a screen of a solid color.
        return Blank(background)

    def get_offset(self, widget: Widget) -> Offset:
        """Get the absolute offset of a given Widget.

        Args:
            widget: A widget

        Returns:
            The widget's offset relative to the top left of the terminal.
        """
        return self._compositor.get_offset(widget)

    def get_widget_at(self, x: int, y: int) -> tuple[Widget, Region]:
        """Get the widget at a given coordinate.

        Args:
            x: X Coordinate.
            y: Y Coordinate.

        Returns:
            Widget and screen region.

        Raises:
            NoWidget: If there is no widget under the screen coordinate.
        """
        return self._compositor.get_widget_at(x, y)

    def get_hover_widgets_at(self, x: int, y: int) -> HoverWidgets:
        """Get the widget, and its region directly under the mouse, and the first
        widget, region pair with a hover style.

        Args:
            x: X Coordinate.
            y: Y Coordinate.

        Returns:
            A pair of (WIDGET, REGION) tuples for the top most and first hover style respectively.

        Raises:
            NoWidget: If there is no widget under the screen coordinate.

        """
        widgets_under_coordinate = iter(self._compositor.get_widgets_at(x, y))
        try:
            top_widget, top_region = next(widgets_under_coordinate)
        except StopIteration:
            raise errors.NoWidget(f"No hover widget under screen coordinate ({x}, {y})")
        if not top_widget._has_hover_style:
            for widget, region in widgets_under_coordinate:
                if widget._has_hover_style:
                    return HoverWidgets((top_widget, top_region), (widget, region))
            return HoverWidgets((top_widget, top_region), None)
        return HoverWidgets((top_widget, top_region), (top_widget, top_region))

    def get_widgets_at(self, x: int, y: int) -> Iterable[tuple[Widget, Region]]:
        """Get all widgets under a given coordinate.

        Args:
            x: X coordinate.
            y: Y coordinate.

        Returns:
            Sequence of (WIDGET, REGION) tuples.
        """
        return self._compositor.get_widgets_at(x, y)

    def get_focusable_widget_at(self, x: int, y: int) -> Widget | None:
        """Get the focusable widget under a given coordinate.

        If the widget directly under the given coordinate is not focusable, then this method will check
        if any of the ancestors are focusable. If no ancestors are focusable, then `None` will be returned.

        Args:
            x: X coordinate.
            y: Y coordinate.

        Returns:
            A `Widget`, or `None` if there is no focusable widget underneath the coordinate.
        """
        try:
            widget, _region = self.get_widget_at(x, y)
        except NoWidget:
            return None

        if widget.has_class("-textual-system") or widget.loading:
            # Clicking Textual system widgets should not focus anything
            return None

        for node in widget.walk_ancestors(with_self=True):
            if isinstance(node, Widget) and node.focusable:
                return node
        return None

    def get_style_at(self, x: int, y: int) -> Style:
        """Get the style under a given coordinate.

        Args:
            x: X Coordinate.
            y: Y Coordinate.

        Returns:
            Rich Style object.
        """
        return self._compositor.get_style_at(x, y)

    def get_widget_and_offset_at(
        self, x: int, y: int
    ) -> tuple[Widget | None, Offset | None]:
        """Get the widget under a given coordinate, and an offset within the original content.

        Args:
            x: X Coordinate.
            y: Y Coordinate.

        Returns:
            Tuple of Widget and Offset, both of which may be None.
        """
        return self._compositor.get_widget_and_offset_at(x, y)

    def find_widget(self, widget: Widget) -> MapGeometry:
        """Get the screen region of a Widget.

        Args:
            widget: A Widget within the composition.

        Returns:
            Region relative to screen.

        Raises:
            NoWidget: If the widget could not be found in this screen.
        """
        return self._compositor.find_widget(widget)

    def clear_selection(self) -> None:
        """Clear any selected text."""
        self.selections = {}
        self._select_state = None

    def _select_all_in_widget(self, widget: Widget) -> None:
        """Select a widget and all its children.

        Args:
            widget: Widget to select.
        """
        select_all = SELECT_ALL
        self.selections = {
            widget: select_all,
            **{child: select_all for child in widget.query("*")},
        }

    @property
    def focus_chain(self) -> list[Widget]:
        """A list of widgets that may receive focus, in focus order."""
        branches, focusable = self._focus_candidates()
        return self._order_focus_candidates(branches, focusable)

    def _focus_candidates(self) -> tuple[dict[Widget, tuple[Widget, ...]], set[Widget]]:
        """Acquire focus membership before demanding ordering geometry."""
        root_node = self.screen

        if (focused := self.focused) is not None:
            for node in focused.walk_ancestors(with_self=True):
                if node._trap_focus:
                    root_node = node
                    break

        # Acquire membership and inherited visibility once. Only branches with
        # an eligible focus target need an ordering position; unfocusable leaf
        # geometry cannot change the resulting chain.
        branches = {root_node: tuple(root_node.displayed_children)}
        focusable: set[Widget] = set()
        node_stack: list[tuple[Iterator[Widget], bool]] = [
            (iter(branches[root_node]), self.visible)
        ]
        pop = node_stack.pop
        push = node_stack.append

        while node_stack:
            children_iterator, parent_visibility = node_stack[-1]
            node = next(children_iterator, None)
            if node is None:
                pop()
            else:
                if node._check_disabled():
                    continue
                node_styles_visibility = node.styles.get_rule("visibility")
                node_is_visible = (
                    node_styles_visibility != "hidden"
                    if node_styles_visibility
                    else parent_visibility  # Inherit visibility if the style is unset.
                )
                if node.is_container and node.allow_focus_children():
                    branches[node] = tuple(node.displayed_children)
                    push((iter(branches[node]), node_is_visible))
                # Same check as `if node.focusable`, but we cached inherited visibility
                # and we also skipped disabled nodes altogether.
                if node_is_visible and node.allow_focus():
                    focusable.add(node)

        # Child branches were acquired after their parents. Prune in reverse
        # so ancestors of offscreen or visibility-overriding targets survive.
        for parent in reversed(branches):
            branches[parent] = tuple(
                child for child in branches[parent]
                if child in focusable or branches.get(child)
            )

        return branches, focusable

    def _order_focus_candidates(
        self, branches: dict[Widget, tuple[Widget, ...]], focusable: set[Widget]
    ) -> list[Widget]:
        """Order the acquired eligible branches in their native coordinates."""
        root_node = next(iter(branches))

        self._compositor.acquire_geometry(
            child for children in branches.values() for child in children
        )
        focus_sorter = attrgetter("_focus_sort_key")
        widgets: list[Widget] = []
        ordered = [iter(sorted(branches[root_node], key=focus_sorter))]
        while ordered:
            node = next(ordered[-1], None)
            if node is None:
                ordered.pop()
                continue
            if node in focusable:
                widgets.append(node)
            if children := branches.get(node):
                ordered.append(iter(sorted(children, key=focus_sorter)))

        return widgets

    def _move_focus(
        self, direction: int = 0, selector: str | type[QueryType] = "*"
    ) -> Widget | None:
        """Move the focus in the given direction.

        If no widget is currently focused, this will focus the first focusable widget.
        If no focusable widget matches the given CSS selector, focus is set to `None`.

        Args:
            direction: 1 to move forward, -1 to move backward, or
                0 to keep the current focus.
            selector: CSS selector to filter
                what nodes can be focused.

        Returns:
            Newly focused widget, or None for no focus. If the return
                is not `None`, then it is guaranteed that the widget returned matches
                the CSS selectors given in the argument.
        """

        if not isinstance(selector, str):
            selector = selector.__name__
        selector_set = parse_selectors(selector)
        focus_chain = self.focus_chain

        # If a widget is maximized we want to limit the focus chain to the visible widgets
        if self.maximized is not None:
            focusable = set(self.maximized.walk_children(with_self=True))
            focus_chain = [widget for widget in focus_chain if widget in focusable]

        filtered_focus_chain = (
            node for node in focus_chain if match(selector_set, node)
        )

        if not focus_chain:
            # Nothing focusable, so nothing to do
            return self.focused
        if self.focused is None:
            # Nothing currently focused, so focus the first one.
            to_focus = next(filtered_focus_chain, None)
            self.set_focus(to_focus)
            return self.focused

        # Ensure focus will be in a node that matches the selectors.
        if not direction and not match(selector_set, self.focused):
            direction = 1

        try:
            # Find the index of the currently focused widget
            current_index = focus_chain.index(self.focused)
        except ValueError:
            # Focused widget was removed in the interim, start again
            self.set_focus(next(filtered_focus_chain, None))
        else:
            # Only move the focus if we are currently showing the focus
            if direction:
                to_focus = None
                chain_length = len(focus_chain)
                for step in range(1, len(focus_chain) + 1):
                    node = focus_chain[
                        (current_index + direction * step) % chain_length
                    ]
                    if match(selector_set, node):
                        to_focus = node
                        break
                self.set_focus(to_focus)

        return self.focused

    def focus_next(self, selector: str | type[QueryType] = "*") -> Widget | None:
        """Focus the next widget, optionally filtered by a CSS selector.

        If no widget is currently focused, this will focus the first focusable widget.
        If no focusable widget matches the given CSS selector, focus is set to `None`.

        Args:
            selector: CSS selector to filter
                what nodes can be focused.

        Returns:
            Newly focused widget, or None for no focus. If the return
                is not `None`, then it is guaranteed that the widget returned matches
                the CSS selectors given in the argument.
        """
        return self._move_focus(1, selector)

    def focus_previous(self, selector: str | type[QueryType] = "*") -> Widget | None:
        """Focus the previous widget, optionally filtered by a CSS selector.

        If no widget is currently focused, this will focus the first focusable widget.
        If no focusable widget matches the given CSS selector, focus is set to `None`.

        Args:
            selector: CSS selector to filter
                what nodes can be focused.

        Returns:
            Newly focused widget, or None for no focus. If the return
                is not `None`, then it is guaranteed that the widget returned matches
                the CSS selectors given in the argument.
        """
        return self._move_focus(-1, selector)

    def maximize(self, widget: Widget, container: bool = True) -> bool:
        """Maximize a widget, so it fills the screen.

        Args:
            widget: Widget to maximize.
            container: If one of the widgets ancestors is a maximizeable widget, maximize that instead.

        Returns:
            `True` if the widget was maximized, otherwise `False`.
        """
        if widget.allow_maximize:
            if container:
                # If we want to maximize the container, look up the dom to find a suitable widget
                for maximize_widget in widget.walk_ancestors():
                    if not isinstance(maximize_widget, Widget):
                        break
                    if maximize_widget.allow_maximize:
                        self.maximized = maximize_widget
                        return True

            self.maximized = widget
            return True
        return False

    def minimize(self) -> None:
        """Restore any maximized widget to normal state."""
        self.maximized = None
        if self.focused is not None:
            self.call_after_refresh(
                self.scroll_to_widget, self.focused, animate=False, center=True
            )

    def get_selected_text(self) -> str | None:
        """Get text under selection.

        Returns:
            Selected text, or `None` if no text was selected.
        """
        self._flush_pending_selection()
        if not self.selections:
            return None

        widget_text: list[str] = []
        for widget, selection in self.selections.items():
            # Filter out widgets that may have been removed since the text was selected
            if (
                widget.is_attached
                and (selected_text_in_widget := widget.get_selection(selection))
                is not None
            ):
                widget_text.extend(selected_text_in_widget)

        selected_text = "".join(widget_text).rstrip("\n")
        return selected_text

    def action_copy_text(self) -> None:
        """Copy selected text to clipboard."""
        selection = self.get_selected_text()
        if selection is None:
            # No text selected
            raise SkipAction()
        self.app.copy_to_clipboard(selection)

    def action_maximize(self) -> None:
        """Action to maximize the currently focused widget."""
        if self.focused is not None:
            self.maximize(self.focused)

    def action_minimize(self) -> None:
        """Action to minimize the currently maximized widget."""
        self.minimize()

    def action_blur(self) -> None:
        """Action to remove focus (if set)."""
        self.set_focus(None)

    async def action_focus(self, selector: str) -> None:
        """An [action](/guide/actions) to focus the given widget.

        Args:
            selector: Selector of widget to focus (first match).
        """
        try:
            node = self.query(selector).first()
        except NoMatches:
            pass
        else:
            if isinstance(node, Widget):
                self.set_focus(node)

    def _reset_focus(
        self, widget: Widget, avoiding: list[Widget] | None = None
    ) -> None:
        """Reset the focus when a widget is removed

        Args:
            widget: A widget that is removed.
            avoiding: Optional list of nodes to avoid.
        """

        avoiding = avoiding or []

        # Make this a NOP if we're being asked to deal with a widget that
        # isn't actually the currently-focused widget.
        if self.focused is not widget:
            return

        # A disabled/hidden widget is absent from native membership. That reset
        # uses sibling declaration order, so full focus geometry is irrelevant.
        # An overridden public chain remains its own selection authority.
        widget_index: int | None = None
        if type(self).focus_chain is _NATIVE_FOCUS_CHAIN:
            branches, focusable = self._focus_candidates()
            focusable_widgets = (
                self._order_focus_candidates(branches, focusable)
                if widget in focusable else list(focusable)
            )
        else:
            focusable_widgets = self.focus_chain
        if not focusable_widgets:
            # If there's nothing to focus... give up now.
            self.set_focus(None)
            return

        try:
            # Find the location of the widget we're taking focus from, in
            # the focus chain.
            widget_index = focusable_widgets.index(widget)
        except ValueError:
            pass
        if widget_index is None:
            # widget is not in focusable widgets
            # It may have been made invisible
            # Move to a sibling if possible
            for sibling in widget.visible_siblings:
                if sibling not in avoiding and sibling.focusable:
                    self.set_focus(sibling)
                    break
            else:
                self.set_focus(None)
            return

        # Now go looking for something before it, that isn't about to be
        # removed, and which can receive focus, and go focus that.
        chosen: Widget | None = None
        for candidate in reversed(
            focusable_widgets[widget_index + 1 :] + focusable_widgets[:widget_index]
        ):
            if candidate not in avoiding:
                chosen = candidate
                break

        # Go with what was found.
        self.set_focus(chosen)

    def _update_focus_styles(
        self, focused: Widget | None = None, blurred: Widget | None = None
    ) -> None:
        """Update CSS for focus changes.

        Args:
            focused: The widget that was focused.
            blurred: The widget that was blurred.
        """
        entered = set(focused.walk_ancestors(with_self=True)) if focused is not None else set()
        exited = set(blurred.walk_ancestors(with_self=True)) if blurred is not None else set()
        self.app.stylesheet.update_focus_within(entered ^ exited)

    def set_focus(
        self,
        widget: Widget | None,
        scroll_visible: bool = True,
        from_app_focus: bool = False,
    ) -> None:
        """Focus (or un-focus) a widget. A focused widget will receive key events first.

        Args:
            widget: Widget to focus, or None to un-focus.
            scroll_visible: Scroll widget into view.
            from_app_focus: True if this focus is due to the app itself having regained
                focus. False if the focus is being set because a widget within the app
                regained focus.
        """
        if widget is self.focused:
            # Widget is already focused
            return

        focused: Widget | None = None
        blurred: Widget | None = None

        if widget is None:
            # No focus, so blur currently focused widget if it exists
            if self.focused is not None:
                self.focused.post_message(events.Blur())
                blurred = self.focused
                self.focused = None
            self.log.debug("focus was removed")
        elif widget.focusable:
            if self.focused != widget:
                if self.focused is not None:
                    # Blur currently focused widget
                    self.focused.post_message(events.Blur())
                    blurred = self.focused
                # Change focus
                self.focused = widget
                # Send focus event
                widget.post_message(events.Focus(from_app_focus=from_app_focus))
                focused = widget

                if scroll_visible:

                    def scroll_to_center(widget: Widget) -> None:
                        """Scroll to center (after a refresh)."""
                        if self.focused is widget and not self.can_view_entire(widget):
                            self.scroll_to_center(widget, origin_visible=True)

                    self.call_later(scroll_to_center, widget)

                self.log.debug(widget, "was focused")

        self._update_focus_styles(focused, blurred)
        self.call_after_refresh(self.refresh_bindings)

    def _extend_compose(self, widgets: list[Widget]) -> None:
        """Insert Textual's own internal widgets.

        Args:
            widgets: The list of widgets to be composed.

        This method adds the tooltip, if required, and also adds the
        container for `Toast`s.
        """
        if not self.app._disable_tooltips:
            widgets.insert(0, Tooltip(id="textual-tooltip"))
        if not self.app._disable_notifications:
            widgets.insert(0, ToastRack(id="textual-toastrack"))

    def _on_mount(self, event: events.Mount) -> None:
        """Set up the tooltip-clearing signal when we mount."""
        self.screen_layout_refresh_signal.subscribe(
            self, self._maybe_clear_tooltip, immediate=True
        )

    @property
    def _layout_refresh_required(self) -> bool:
        """Explicit layout and released source requests need the same refresh.

        A held source retains its members after the timer consumes the layout
        intent. Releasing that source makes those original requests actionable;
        it doesn't need a second Layout message to recreate their intent.
        """
        return self._layout_required or self._has_actionable_layout_requests(
            self._held_layout_requests()
        )

    @property
    def _refresh_requested(self) -> bool:
        """Whether pending screen work requires the timer regardless of damage."""
        return bool(
            self._layout_refresh_required
            or self._scroll_required
            or self._repaint_required
            or self._recompose_required
        )

    @property
    def _refresh_pending(self) -> bool:
        """Whether the existing scene owners still have an unpainted update."""
        return bool(
            self._refresh_requested or self._dirty_widgets or self._compositor._dirty_regions
        )

    async def _on_idle(self, event: events.Idle) -> None:
        # Check for any widgets marked as 'dirty' (needs a repaint)
        event.prevent_default()
        # A held-only dirty frame still needs its original preparation hook to
        # decide timer progress. This acquisition is not callback admission.
        # Paint reacquires after queued source/layout work has had time to run.
        if not self.app._batch_count and self.is_current:
            if self._refresh_requested or self._dirty_widgets:
                self._update_timer.resume()
            elif self._compositor._dirty_regions:
                roots = tuple(root for _, roots in self._prepare_visible_screens() for root in roots)
                if (self._refresh_requested or self._dirty_widgets
                        or self._compositor._exclude_regions(
                            self._compositor._dirty_regions,
                            tuple(region for root in roots
                                  for region in root.screen._compositor.deferred_regions((root,))),
                        )):
                    self._update_timer.resume()

        self._invoke_and_clear_callbacks()

    def _prepare_compositor_refresh(self) -> tuple[Widget, ...]:
        """Prepare pending frame work and return subtrees whose paint is held.

        This owns frame preparation and actionable-damage discovery. Callback
        admission consumes the resulting pending damage and source mutation;
        it must not invoke preparation to manufacture another frame decision.
        """
        return ()

    def _layout_mutation_roots(self) -> tuple[Widget, ...]:
        """Subtrees borrowing their committed geometry during source mutation."""
        return ()

    def _on_frame_published(self, deferred_roots: tuple[Widget, ...]) -> None:
        """Observe an actual displayed update with its acquired admission roots."""

    def _using_presentation_inputs(self) -> AbstractContextManager[None]:
        """Lend acquired inputs only to synchronous preparation and rendering.

        Layout and inline measurement have already returned. The borrow ends
        before display/writer callbacks, and never certifies a later frame or
        independently changing inputs. Ordinary screens keep live queries.
        """
        return nullcontext()

    def _prepare_visible_screens(
        self, screens: tuple[Screen, ...] | None = None,
    ) -> tuple[tuple[Screen, tuple[Widget, ...]], ...]:
        """Acquire the original visible stack for frame preparation and paint."""
        if screens is None:
            screens = (*self.app._background_screens, self) if self is self.app.screen else (self,)
        return tuple((screen, screen._prepare_compositor_refresh()) for screen in screens)

    def _after_refresh_pending(
        self, screen, roots: tuple[Widget, ...], *,
        refresh_requested: dict[Screen, bool], refresh_pending: bool,
    ) -> bool:
        """Screen-owned work retains the original whole-frame admission."""
        return MessagePump._after_refresh_pending(
            self, screen, roots, refresh_requested=refresh_requested,
            refresh_pending=refresh_pending,
        )

    def _compositor_refresh(self) -> None:
        """Publish admitted damage, retaining held subtree damage in Compositor."""
        app = self.app
        if app._batch_count:
            return
        background_screens = app._background_screens
        if self is app.screen and app.is_inline:
            inline_height = app._get_inline_height()
        foreground = self is app.screen
        screens = (*background_screens, self) if foreground else (self,)
        damage = None
        # Pixel exclusions continue through writer admission and pointer
        # checks. Input borrows have the narrower preparation/render lifetime:
        # a display callback may change the actual source or presentation.
        with ExitStack() as frame:
            with ExitStack() as inputs:
                for screen in screens:
                    inputs.enter_context(screen._using_presentation_inputs())
                cohort = self._prepare_visible_screens(screens)
                deferred_roots = tuple(root for _, roots in cohort for root in roots)
                exclusions = set(
                    region for screen, roots in cohort
                    for region in screen._compositor.deferred_regions(roots)
                )
                # A backdrop and foreground share the same output cells.
                # Resolve displacement dependencies across that exact acquired
                # stack before any renderer can consume one screen's damage.
                while True:
                    previous = exclusions.copy()
                    for screen, _ in cohort:
                        exclusions.update(screen._compositor.publication_exclusions(exclusions, deferred_roots))
                    if exclusions == previous:
                        break
                excluded_regions = tuple(exclusions)
                if foreground:
                    background_geometry = {
                        screen: (screen._compositor._layout_map,
                                 screen._compositor._dirty_regions.copy())
                        for screen in background_screens
                    }
                    # BackgroundScreen can render inside the foreground's
                    # renderer. Both borrow this exact acquired admission.
                    for screen, _ in cohort:
                        frame.enter_context(screen._compositor._using_exclusions(excluded_regions))
                    if app.is_inline:
                        clear = (
                            app._previous_inline_height is not None
                            and inline_height < app._previous_inline_height
                        )
                        update = self._compositor.render_inline(
                            app.size.with_height(max(inline_height, app._previous_inline_height or 0)
                                                 if deferred_roots else inline_height),
                            screen_stack=background_screens, clear=clear,
                            excluded_regions=excluded_regions,
                            deferred_roots=deferred_roots,
                        )
                        if update is not None and not deferred_roots:
                            app._previous_inline_height = inline_height
                    else:
                        update = self._compositor.render_update(
                            screen_stack=background_screens,
                            excluded_regions=excluded_regions,
                            deferred_roots=deferred_roots,
                        )
                    if update is not None:
                        for screen in background_screens:
                            arranged, background_damage = background_geometry[screen]
                            update.bind_publication(screen._compositor, arranged, background_damage,
                                                    update.rendered_regions, excluded_regions, deferred_roots)
                elif self in background_screens and self._compositor._dirty_regions:
                    damage = self._compositor._exclude_regions(
                        self._compositor._dirty_regions, excluded_regions,
                    )

            if foreground:
                if update is not None:
                    app._display(self, update)
                    if update.admitted:
                        self._on_frame_published(deferred_roots)
                if not self._compositor._interaction_deferred(*app.mouse_position):
                    app._update_mouse_over(self)
            elif damage is not None:
                # The foreground owns terminal publication of the same
                # backdrop damage. Transfer intent without consuming held work.
                if damage:
                    self._set_dirty(*damage)
                    app.screen.refresh(*damage)
                    # The foreground's actual output update owns consumption;
                    # forwarding damage is not a display acknowledgment.
                self._dirty_widgets.clear()
                if not self._compositor._interaction_deferred(*app.mouse_position):
                    app._update_mouse_over(self)
        if foreground:
            if background_screens:
                for screen, _ in cohort:
                    screen._release_paint()
            self._dirty_widgets.clear()

    def _on_timer_update(self) -> None:
        """Called by the _update_timer."""
        self._update_timer.pause()
        if self.is_current and not self.app._batch_count:
            self._flush_pending_selection()
            if self._repaint_required:
                # Include the acquired repaint in this layout/publication,
                # rather than painting the same scene again afterward.
                self._dirty_widgets.clear()
                self._dirty_widgets.add(self)
                self._repaint_required = False
            # Consume the acquired intents before layout. Resize watchers and
            # immediate layout-signal subscribers may request another frame
            # synchronously; those requests belong to the next admission.
            layout_required, scroll_required = self._layout_refresh_required, self._scroll_required
            self._layout_required = False
            self._scroll_required = False
            if layout_required or scroll_required:
                # Layout may compensate positions or publish immediate signals
                # before returning. The timer owns their final publication;
                # direct layout callers retain their ordinary immediate paint.
                with self.app.batch_update():
                    self._refresh_layout(scroll=scroll_required)

            if self._dirty_widgets:
                self._compositor.update_widgets(self._dirty_widgets)
            if (layout_required or scroll_required
                    or self._dirty_widgets or self._compositor._dirty_regions):
                # Preparation has source/follow effects even if layout left no
                # damage. Acquire once, after all synchronous layout effects,
                # rather than rendering held damage twice in the same timer.
                self._compositor_refresh()

            if self._recompose_required:
                self._recompose_required = False
                self.call_next(self.recompose)

        if self._callbacks:
            self.call_next(self._invoke_and_clear_callbacks)

    def _sender_refresh_pending(
        self, sender: Widget, roots: tuple[Widget, ...], *,
        refresh_requested: dict[Screen, bool],
    ) -> bool:
        """Admit the original spatial sender, including its backdrop publication."""
        if roots and (
            set(sender.walk_ancestors(with_self=True)).intersection(roots)
            or any(sender in root.walk_ancestors(with_self=True) for root in roots)
        ):
            return True
        owner = sender.screen
        for screen in (self, owner) if owner is not self else (self,):
            # An independently owned backdrop or inactive sender screen has
            # its own answer, acquired once when this pass first consumes it.
            if screen not in refresh_requested:
                refresh_requested[screen] = screen._refresh_requested
            if refresh_requested[screen]:
                return True
            if any(sender in widget.walk_ancestors(with_self=True)
                   for widget in screen._dirty_widgets):
                return True
            if screen._compositor.pending_for(sender):
                return True
        return False

    def _invoke_and_clear_callbacks(self) -> None:
        """Admit painted senders back to their own original message pumps."""
        if self.app._batch_count or not self._callbacks:
            return
        # A callback waits for its original pending publication. It does not
        # start preparation, move a follow position or acquire CSS readiness.
        # Held pixels still own dirty regions; retained pixels do not release
        # a source writer, whose original mutation owner remains independent.
        roots = tuple(root
            for screen in (*self.app._background_screens, self)
            for root in screen._layout_mutation_roots()) if self.is_current else ()
        # Acquire the original virtual queries once for this synchronous pass.
        # Sender queueing doesn't dispatch callbacks here; their original pumps
        # execute them after this admission returns. No answer outlives the pass.
        refresh_requested = {self: self._refresh_requested}
        refresh_pending = self._refresh_pending
        index = 0
        for _ in range(len(self._callbacks)):
            if self.app._batch_count or index >= len(self._callbacks):
                return
            callback, sender = self._callbacks[index]
            if self.is_current and sender._after_refresh_pending(
                self, roots, refresh_requested=refresh_requested,
                refresh_pending=refresh_pending,
            ):
                index += 1
                continue
            self._callbacks.pop(index)
            sender.call_later(callback)

    def _invoke_later(self, callback: CallbackType, sender: MessagePump) -> None:
        """Enqueue a callback to be invoked after the screen is repainted.

        Args:
            callback: A callback.
            sender: The sender (active message pump) of the callback.
        """

        self._callbacks.append((callback, sender))
        self.check_idle()

    def _push_result_callback(
        self,
        requester: MessagePump,
        callback: ScreenResultCallbackType[ScreenResultType] | None,
        future: asyncio.Future[ScreenResultType | None] | None = None,
    ) -> None:
        """Add a result callback to the screen.

        Args:
            requester: The object requesting the callback.
            callback: The callback.
            future: A Future to hold the result.
        """
        self._result_callbacks.append(
            ResultCallback[Optional[ScreenResultType]](requester, callback, future)
        )

    async def _message_loop_exit(self) -> None:
        await super()._message_loop_exit()
        self._compositor.clear()
        self._callbacks.clear()
        self._layout_widgets.clear()
        self._dirty_widgets.clear()
        self._dirty_regions.clear()
        self._arrangement_cache.clear()
        self.screen_layout_refresh_signal.unsubscribe(self)
        self._nodes._clear()

    def _pop_result_callback(self) -> None:
        """Remove the latest result callback from the stack."""
        self._result_callbacks.pop()

    def _use_viewport_layout(self) -> bool:
        """Opt in to viewport geometry with lazy acquisition of reader paths."""
        return False

    def _layout_geometry_targets(self) -> tuple[Widget, ...]:
        """Additional native geometry required by a viewport-layout transaction."""
        return ()

    def _held_layout_requests(self) -> dict[DOMNode, set[Widget]]:
        """Borrow pending requests whose subtree still owns committed geometry."""
        if not self._layout_widgets:
            return {}
        mutation_roots = self._layout_mutation_roots()
        return {
            owner: held for owner, members in self._layout_widgets.items()
            if (held := {
                member for member in members
                if set(member.walk_ancestors(with_self=True)).intersection(mutation_roots)
            })
        } if mutation_roots else {}

    def _has_actionable_layout_requests(
        self, held: dict[DOMNode, set[Widget]]
    ) -> bool:
        """Whether the original pending source requests can affect geometry."""
        return any(
            not members <= held.get(owner, set())
            for owner, members in self._layout_widgets.items()
        )

    def _refresh_layout(self, size: Size | None = None, scroll: bool = False) -> None:
        """Refresh the layout (can change size and positions of widgets)."""
        size = self.outer_size if size is None else size
        if self.app.is_inline:
            size = size.with_height(self.app._get_inline_height())
        if not size:
            return
        self._compositor.update_widgets(self._dirty_widgets)
        self._update_timer.pause()
        ResizeEvent = events.Resize

        try:
            geometry_targets = self._layout_geometry_targets()
            held_layout = self._held_layout_requests() if scroll else {}
            # Held requests remain pending for release. They cannot alter the
            # committed subtree during scrolling; only actionable requests
            # require layout beyond the original visible-scroll traversal.
            if scroll and not self._has_actionable_layout_requests(held_layout):
                exposed_widgets = self._compositor.reflow_visible(
                    self, size, retain_geometry=geometry_targets,
                )
                if exposed_widgets:
                    layers = self._compositor.layers
                    for widget, geometry in layers:
                        if widget in exposed_widgets:
                            if widget._size_updated(
                                geometry.region.size, geometry.virtual_size,
                                geometry.container_size, layout=False
                            ):
                                widget.post_message(
                                    ResizeEvent(
                                        widget.outer_size, widget.virtual_size, widget.container_size
                                    )
                                )

            else:
                viewport_layout = self._use_viewport_layout()
                if viewport_layout:
                    hidden, shown = self._compositor.reflow(
                        self, size, visible_only=True, retain_geometry=geometry_targets,
                    )
                else:
                    hidden, shown = self._compositor.reflow(self, size)
                self._layout_widgets = self._held_layout_requests()
                Hide = events.Hide
                Show = events.Show

                for widget in hidden:
                    widget.post_message(Hide())

                layers = self._compositor.layers
                for widget, geometry in layers:
                    size_changed = widget._size_updated(
                        geometry.region.size, geometry.virtual_size, geometry.container_size)
                    if widget in shown or size_changed:
                        widget.post_message(
                            ResizeEvent(widget.outer_size, widget.virtual_size, widget.container_size)
                        )

                for widget in shown:
                    widget.post_message(Show())

        except Exception as error:
            self.app._handle_exception(error)
            return

        if self.is_current:
            self._compositor_refresh()

        if self.app._dom_ready:
            self.screen_layout_refresh_signal.publish(self.screen)
        else:
            self.app.post_message(events.Ready())
            self.app._dom_ready = True

    async def _on_update(self, message: messages.Update) -> None:
        message.stop()
        message.prevent_default()
        widget = message.widget
        assert isinstance(widget, Widget)
        if widget._pruning or widget._closed:
            return

        if self in self._compositor:
            self._dirty_widgets.add(widget)
            self.check_idle()

    async def _on_layout(self, message: messages.Layout) -> None:
        message.stop()
        message.prevent_default()

        layout_required = False
        widget: DOMNode = message.widget
        if widget._pruning or widget._closed:
            return
        for ancestor in message.widget.walk_ancestors():
            if not isinstance(ancestor, Widget):
                break
            if ancestor not in self._layout_widgets:
                self._layout_widgets[ancestor] = set()
            if widget not in self._layout_widgets:
                self._layout_widgets[ancestor].add(widget)
                layout_required = True
            if not ancestor.styles.auto_dimensions:
                break
            widget = ancestor

        if not self._layout_required:
            # A prior frame keeps held requests but consumes its timer intent.
            # Membership is not a new-source notification: after release the
            # SAME pending request becomes actionable under current roots.
            if layout_required or self._layout_refresh_required:
                self._layout_required = True
                self.check_idle()

    async def _on_update_scroll(self, message: messages.UpdateScroll) -> None:
        message.stop()
        message.prevent_default()
        self._scroll_required = True
        self.check_idle()

    def _forget_pruned_widgets(self, widgets: set[Widget]) -> None:
        """Retire original scene and interaction resources before teardown."""
        widgets = self._forget_widget_geometry(widgets)
        self._retire_selection(widgets)
        self.app._retire_pointer_widgets(widgets)

    def _retire_selection(self, widgets: set[Widget]) -> None:
        """Keep surviving ranges without retaining a removed pointer endpoint."""
        self.selections = {
            widget: selection
            for widget, selection in self.selections.items()
            if widget not in widgets
        }
        if (
            self._select_state is not None
            and self._select_state.references_retired(widgets)
        ):
            self._select_state = None

    def _forget_widget_geometry(self, widgets: set[Widget]) -> set[Widget]:
        """Retire scene and queued damage owners without dropping repaint regions."""
        widgets = self._compositor.discard_widgets(widgets)
        self._dirty_widgets.difference_update(widgets)
        for ancestor, children in tuple(self._layout_widgets.items()):
            if ancestor in widgets:
                self._layout_widgets.pop(ancestor)
            else:
                children.difference_update(widgets)
        return widgets

    def _get_inline_height(self, size: Size) -> int:
        """Get the inline height (number of lines to display when running inline mode).

        Args:
            size: Size of the terminal

        Returns:
            Height for inline mode.
        """
        height_scalar = self.styles.height
        if height_scalar is None or height_scalar.is_auto:
            inline_height = self.get_content_height(size, size, size.width)
        else:
            inline_height = int(height_scalar.resolve(size, size))
        inline_height += self.styles.gutter.height
        min_height = self.styles.min_height
        max_height = self.styles.max_height
        if min_height is not None:
            inline_height = max(inline_height, int(min_height.resolve(size, size)))
        if max_height is not None:
            inline_height = min(inline_height, int(max_height.resolve(size, size)))
        inline_height = min(self.app.size.height, inline_height)
        return inline_height

    def _screen_resized(self, size: Size) -> None:
        """Called by App when the screen is resized."""
        if self.stack_updates and self.is_attached:
            self._refresh_layout(size)

    def _on_screen_resume(self, event: events.ScreenResume) -> None:
        """Screen has resumed."""
        if self.app.SUSPENDED_SCREEN_CLASS:
            self.remove_class(self.app.SUSPENDED_SCREEN_CLASS)

        self.stack_updates += 1

        self.app._refresh_notifications()
        size = self.app.size

        self._update_auto_focus()

        if self.is_attached:

            if event.refresh_styles:
                self.update_node_styles(animate=False)
            if self._size != size:
                self._refresh_layout(size)
            self.refresh()

    async def _compose(self) -> None:
        await super()._compose()
        self._update_auto_focus()

    def _update_auto_focus(self) -> None:
        """Update auto focus."""
        if self.app.app_focus:
            auto_focus = (
                self.app.AUTO_FOCUS if self.AUTO_FOCUS is None else self.AUTO_FOCUS
            )
            if auto_focus and self.focused is None:
                for widget in self.query(auto_focus):
                    if widget.focusable:
                        widget.has_focus = True
                        self.set_focus(widget)
                        break

    def _on_screen_suspend(self) -> None:
        """Screen has suspended."""
        # Releases now route to another Screen. Retain the copyable range,
        # but retire the press and its auto-scroll through the original owner.
        self._mouse_down_offset = None
        if self.app.SUSPENDED_SCREEN_CLASS:
            self.add_class(self.app.SUSPENDED_SCREEN_CLASS)
        self.app._set_mouse_over(None, None)
        self._clear_tooltip()
        self.stack_updates += 1
        if not self.RETAIN_INACTIVE_PRESENTATION:
            self.call_later(self._retire_inactive_presentation)
        elif not self.RETAIN_INACTIVE_PAINT:
            self.call_later(self._retire_inactive_paint)

    RETAIN_INACTIVE_PAINT: ClassVar[bool] = True
    """Keep paint caches in inactive modes. Opt out to retain geometry but repaint
    from the model on resume. Visible backdrops are never retired.
    """

    RETAIN_INACTIVE_PRESENTATION: ClassVar[bool] = True
    """Retain derived paint/measurement caches while outside the visible stack.

    Applications with many model-backed modes may opt out. Content, rules,
    selection and native widget lifetimes are preserved; resume recomputes the
    presentation. A screen still used as a visible backdrop is never retired.
    """

    def _retire_inactive_paint(self) -> None:
        if self.is_current or self._closing or self in self.app._background_screens:
            return
        for widget in self.walk_children(with_self=True):
            widget._release_paint()
        self._repaint_required = True

    def _retire_inactive_presentation(self) -> None:
        if self.is_current or self._closing or self in self.app._background_screens:
            return
        for widget in self.walk_children(with_self=True):
            widget._release_presentation()
        self._compositor.clear()
        self._dirty_widgets.clear()
        self._layout_widgets.clear()
        self._layout_required = True
        self._repaint_required = True

    SUBTREE_GEOMETRY_CACHE_ENTRIES: ClassVar[int] = Compositor.DEFAULT_SUBTREE_GEOMETRY_CACHE_ENTRIES
    """Maximum retained opt-in subtree projections; zero disables retention.

    This is an application-tunable working-set budget, not a layout limit.
    Lower values trade reuse for memory without changing geometry or content.
    """

    async def _on_resize(self, event: events.Resize) -> None:
        event.stop()
        self._screen_resized(event.size)
        for screen in self.app._background_screens:
            screen._screen_resized(event.size)

        horizontal_breakpoints = (
            self.app.HORIZONTAL_BREAKPOINTS
            if self.HORIZONTAL_BREAKPOINTS is None
            else self.HORIZONTAL_BREAKPOINTS
        ) or []

        vertical_breakpoints = (
            self.app.VERTICAL_BREAKPOINTS
            if self.VERTICAL_BREAKPOINTS is None
            else self.VERTICAL_BREAKPOINTS
        ) or []

        if horizontal_breakpoints or vertical_breakpoints:
            width, height = event.size
            breakpoints = {
                breakpoint: False
                for _, breakpoint in (horizontal_breakpoints + vertical_breakpoints)
            }

            for breakpoint in self._get_breakpoint_classes(
                width, horizontal_breakpoints
            ):
                breakpoints[breakpoint] = True

            for breakpoint in self._get_breakpoint_classes(
                height, vertical_breakpoints
            ):
                breakpoints[breakpoint] = True

            self.update_classes(breakpoints, animate=False)

    def _get_breakpoint_classes(
        self, dimension: int, breakpoints: list[tuple[int, str]]
    ) -> set[str]:
        """Get breakpoint classes for given dimension.

        Args:
            dimension: Size in cells.
            breakpoints: Associated breakpoints.

        Returns:
            A set containing a breakpoint, or an empty set if none apply.
        """
        for breakpoint, class_name in sorted(breakpoints, reverse=True):
            if dimension >= breakpoint:
                return {class_name}
        return set()

    def _update_tooltip(self, widget: Widget) -> None:
        """Update the content of the tooltip."""
        try:
            tooltip = self.get_child_by_type(Tooltip)
        except NoMatches:
            pass
        else:
            if tooltip.display and self._tooltip_widget is widget:
                self._handle_tooltip_timer(widget)

    def _clear_tooltip(self) -> None:
        """Unconditionally clear any existing tooltip."""
        try:
            tooltip = self.get_child_by_type(Tooltip)
        except NoMatches:
            return
        if tooltip.display:
            if self._tooltip_timer is not None:
                self._tooltip_timer.stop()
            tooltip.display = False

    def _maybe_clear_tooltip(self, _) -> None:
        """Check if the widget under the mouse cursor still pertains to the tooltip.

        If they differ, the tooltip will be removed.
        """
        # If there's a widget associated with the tooltip at all...
        if self._tooltip_widget is not None:
            # ...look at what's currently under the mouse.
            try:
                under_mouse, _ = self.get_widget_at(*self.app.mouse_position)
            except NoWidget:
                pass
            else:
                # If it's not the same widget...
                if under_mouse is not self._tooltip_widget:
                    # ...clear the tooltip.
                    self._clear_tooltip()

    def _handle_tooltip_timer(self, widget: Widget) -> None:
        """Called by a timer from _handle_mouse_move to update the tooltip.

        Args:
            widget: The widget under the mouse.
        """

        try:
            tooltip = self.get_child_by_type(Tooltip)
        except NoMatches:
            pass
        else:
            tooltip_content: RenderableType | None = None
            for node in widget.walk_ancestors(with_self=True):
                if not isinstance(node, Widget):
                    break
                if node.tooltip is not None:
                    tooltip_content = node.tooltip
                    break

            if tooltip_content is None:
                tooltip.display = False
            else:
                tooltip.display = True
                tooltip.absolute_offset = self.app.mouse_position
                tooltip.update(tooltip_content)

    def _handle_mouse_move(self, event: events.MouseMove) -> AwaitComplete:
        event.widget = None
        completion = AwaitComplete.nothing()
        hover_widget: Widget | None = None
        try:
            if self.app.mouse_captured:
                widget = self.app.mouse_captured
                region = self.find_widget(widget).region
            else:
                (widget, region), hover = self.get_hover_widgets_at(event.x, event.y)
                if hover is not None:
                    hover_widget = hover[0]
        except errors.NoWidget:
            self.app._set_mouse_over(None, None)
            if self._tooltip_timer is not None:
                self._tooltip_timer.stop()
            if not self.app._disable_tooltips:
                try:
                    self.get_child_by_type(Tooltip).display = False
                except NoMatches:
                    pass
        else:
            event.widget = widget
            self.app._set_mouse_over(widget, hover_widget)
            self.update_pointer_shape()
            widget.hover_style = event.style
            if widget is self:
                routed_event = event._apply_offset(0, 0)
                routed_event._set_forwarded()
                completion = self._post_message_and_wait(routed_event)
            else:
                mouse_event = self._translate_mouse_move_event(event, widget, region)
                mouse_event._set_forwarded()
                completion = widget._forward_event(mouse_event)

            if not self.app._disable_tooltips:
                try:
                    tooltip = self.get_child_by_type(Tooltip)
                except NoMatches:
                    pass
                else:
                    if self._tooltip_widget != widget or not tooltip.display:
                        self._tooltip_widget = widget
                        if self._tooltip_timer is not None:
                            self._tooltip_timer.stop()

                        self._tooltip_timer = self.set_timer(
                            self.app.TOOLTIP_DELAY,
                            partial(self._handle_tooltip_timer, widget),
                            name="tooltip-timer",
                        )
                    else:
                        tooltip.display = False
        self.screen.update_pointer_shape()
        return completion

    @staticmethod
    def _translate_mouse_move_event(
        event: events.MouseMove, widget: Widget, region: Region
    ) -> events.MouseMove:
        """
        Returns a mouse move event whose relative coordinates are translated to
        the origin of the specified region.
        """
        return events.MouseMove(
            widget,
            event._x - region.x,
            event._y - region.y,
            event._delta_x,
            event._delta_y,
            event.button,
            event.shift,
            event.meta,
            event.ctrl,
            screen_x=event._screen_x,
            screen_y=event._screen_y,
            style=event.style,
        )

    def _start_auto_scroll(
        self,
        widget: Widget,
        direction: Literal[+1, -1],
        speed: float = 1.0,
    ) -> None:
        """Start (or update) auto scrolling.

        Args:
            widget: Container widget to scroll.
            direction: Direction: `+1` for up, `-1` for down.
            speed: The scroll speed as a factor of the maximum.
        """
        assert speed > 0, "Speed should be positive and non-zero"

        def _auto_scroll_y(widget: Widget, direction: float) -> None:
            """Scroll a container a single line in the given direction.

            Args:
                widget: Container widgets to scroll.
                direction: Lines to scroll.
            """
            if self._selecting:
                # Update scroll position
                previous_offset = widget.scroll_offset
                widget.scroll_y += direction
                widget.scroll_target_y = widget.scroll_y
                # Mouse moves have already updated selection. Fractional
                # auto-scroll ticks often leave the painted row unchanged;
                # traversing the entire selected transcript a second time
                # cannot change its highlights until the cell offset moves.
                if widget.scroll_offset != previous_offset:
                    self._update_select()

        # Replace current timer
        self._stop_auto_scroll()

        # Lines to scroll per frame (may be fractional)
        lines_to_scroll = (
            direction * self.app.SELECT_AUTO_SCROLL_SPEED * self.app.frame_interval * speed
        )
        # Callable to perform scroll
        scroll_callback = partial(_auto_scroll_y, widget, lines_to_scroll)
        # The mouse move has already calculated its selection. An immediate
        # scroll_callback also recomputes the same (potentially large) range
        # before the first frame can paint. Begin on the next timer tick: it
        # is one frame away, and continuing to hold at the edge still scrolls.
        self._auto_select_scroll_timer = self.set_interval(
            self.app.frame_interval, scroll_callback
        )

    def _stop_auto_scroll(self) -> None:
        """Stop any auto scrolling."""
        if self._auto_select_scroll_timer is not None:
            self._auto_select_scroll_timer.stop()
            self._auto_select_scroll_timer = None

    def _check_auto_scroll(
        self,
        select_widget: Widget,
        mouse_coordinate: tuple[float, float],
        delta_y: float,
    ) -> None:
        """Check auto-scrolling when selecting.

        This will start, update, or stop a timer used to move the scroll position.

        Args:
            select_widget: The widget under the mouise pointer.
            mouse_coordinate: The screen-space mouse pointer.
            delta_y: Change in mouse y since previous mouse move.
        """

        if not self.app.ENABLE_SELECT_AUTO_SCROLL:
            # Disabled by app
            return

        if self._auto_select_scroll_timer is None and abs(delta_y) < 1:
            # Mouse has moved horizontally, not vertically, so we assume the user doesn't want to scroll
            return

        mouse_x, mouse_y = mouse_coordinate
        mouse_offset = Offset(int(mouse_x), int(mouse_y))

        # We want to find any scrollable regions further up the DOM,
        # and apply auto scrolling if we are in a region at the top or bottom
        for ancestor in select_widget.walk_ancestors(with_self=True):
            if not isinstance(ancestor, Widget):
                break
            if not ancestor.allow_vertical_scroll:
                # Can't scroll, so check the next ancestor
                continue
            ancestor_region = ancestor.content_region
            scroll_lines = self.app.SELECT_AUTO_SCROLL_LINES
            up_region, down_region = get_auto_scroll_regions(
                ancestor_region,
                auto_scroll_lines=scroll_lines,
            )
            if mouse_offset in up_region:
                # Mouse is in the up region
                if ancestor.scroll_y > 0:
                    # And there is room to scroll
                    # Speed increases the closer we are to the edge
                    speed = (scroll_lines - (mouse_y - up_region.y)) / scroll_lines
                    if speed:
                        self._start_auto_scroll(ancestor, -1, speed)
                        return
            elif mouse_offset in down_region:
                # Mouse is in the down region
                if ancestor.scroll_y < ancestor.max_scroll_y:
                    # And there is room to scroll
                    speed = (mouse_y - down_region.y) / scroll_lines
                    if speed:
                        self._start_auto_scroll(ancestor, +1, speed)
                        return
        # Nothing to auto scroll, so stop the timer
        self._stop_auto_scroll()

    def _update_select(self) -> None:
        """Update select for a screen-space offset (typically the mouse position)."""
        self._watch__select_state(self._select_state)

    def _forward_event(self, event: events.Event) -> AwaitComplete:
        if event.is_forwarded:
            return AwaitComplete.nothing()
        event._set_forwarded()
        completion = AwaitComplete.nothing()

        if isinstance(event, (events.Enter, events.Leave)):
            self.post_message(event)

        elif isinstance(event, events.MouseMove):
            event.style = self.get_style_at(event.screen_x, event.screen_y)
            completion = self._handle_mouse_move(event)

            if self._selecting and self._select_state is not None:

                select_widget, select_offset = self.get_widget_and_offset_at(
                    event.x, event.y
                )
                if select_widget is not None:
                    if select_offset is not None:
                        content_widget = select_widget
                        content_offset = select_offset
                        container = (
                            content_widget
                            if isinstance(content_widget, Screen)
                            else content_widget.parent
                        )
                    else:
                        content_widget = None
                        container = select_widget
                        content_offset = None

                    self._select_state = self._select_state.update_end(
                        event.screen_offset,
                        SelectEnd(container, content_widget, content_offset),
                    )

                if select_widget is not None:
                    self._check_auto_scroll(
                        select_widget,
                        (event.pointer_screen_x, event.pointer_screen_y),
                        event.delta_y,
                    )
                else:
                    self._stop_auto_scroll()

        elif isinstance(event, events.MouseEvent):
            event.widget = None
            if isinstance(event, events.MouseUp) and event.button == 1:
                self._flush_pending_selection()
                if (
                    self._mouse_down_offset is not None
                    and self._mouse_down_offset == event.screen_offset
                ):
                    # A click elsewhere should clear the selection
                    select_widget, select_offset = self.get_widget_and_offset_at(
                        event.x, event.y
                    )
                    # Exclude scrollbars, so the user may navigate without clearing the selection
                    if select_widget is None or not select_widget.has_class(
                        "-textual-system"
                    ):
                        self.clear_selection()

                self._mouse_down_offset = None
                self.post_message(events.TextSelected())

            elif (
                isinstance(event, events.MouseDown)
                and event.button == 1
                and not self.app.mouse_captured
            ):
                self._mouse_down_offset = event.screen_offset
                select_widget, select_offset = self.get_widget_and_offset_at(
                    event.x, event.y
                )

                if (
                    select_widget is not None
                    and select_widget.allow_select
                    and self.screen.allow_select
                    and self.app.ALLOW_SELECT
                ):
                    if select_offset is not None:
                        content_widget = select_widget
                        content_offset = select_offset
                        container = (
                            content_widget
                            if isinstance(content_widget, Screen)
                            else content_widget.parent
                        )
                    else:
                        content_widget = None
                        container = select_widget
                        content_offset = None

                    self._select_state = SelectState(
                        event.screen_offset,
                        start=SelectStart(
                            container,
                            event.screen_offset - container.region.offset,
                            container.region.offset,
                            container.scroll_offset,
                            content_widget=content_widget,
                            content_offset=content_offset,
                        ),
                    )
                else:
                    self._select_state = None

            try:
                if self.app.mouse_captured:
                    widget = self.app.mouse_captured
                    region = self.find_widget(widget).region
                else:
                    widget, region = self.get_widget_at(event.x, event.y)
            except errors.NoWidget:
                self.set_focus(None)
            else:
                if isinstance(event, events.MouseDown):
                    focusable_widget = self.get_focusable_widget_at(event.x, event.y)
                    if (
                        focusable_widget is not None
                        and focusable_widget.focus_on_click()
                    ):
                        self.set_focus(focusable_widget, scroll_visible=False)
                event.style = self.get_style_at(event.screen_x, event.screen_y)
                if widget.loading:
                    return completion
                event.widget = widget
                if widget is self:
                    event._set_forwarded()
                    routed_event = event._apply_offset(0, 0)
                    routed_event._set_forwarded()
                    completion = self._post_message_and_wait(routed_event)
                else:
                    completion = widget._forward_event(
                        event._apply_offset(-region.x, -region.y)
                    )

        else:
            self.post_message(event)
        self.update_pointer_shape()
        return completion

    def _key_escape(self) -> None:
        self.clear_selection()

    def _watch__mouse_down_offset(self, offset: Offset | None) -> None:
        if offset is None:
            self._stop_auto_scroll()

    def _interaction_widgets(self) -> Iterator[Widget]:
        """Borrow current interaction custody without projecting selected ranges."""
        yield from self.selections
        if self._select_state is not None:
            yield from self._select_state._walk_involved_widgets()
        for widget in (self.focused, self.app.mouse_captured):
            if widget is not None:
                yield widget

    def _watch__select_state(self, select_state: SelectState | None) -> None:
        """Respond to user-initiated selection change.

        Args:
            select_state: Current selection state.
        """
        if select_state is None:
            self._stop_auto_scroll()
        if (
            select_state is not None
            and select_state.end is not None
            and self is self.app.screen
        ):
            # The application may already have another raw drag position
            # queued. Deliver all mouse events, but don't repeatedly traverse
            # thousands of selected widgets for positions superseded before
            # painting. The original callback, copy, mouse-up and paint
            # boundaries flush this projection. Routed handler completion is
            # not a selection publication boundary.
            try:
                pending = self.app._peek_message()
            except MessagePumpClosed:
                pending = None
            if (
                type(pending) is events.MouseMove
                and pending.button == 1
                and not pending.is_forwarded
            ):
                self._selection_update_pending = True
                return

        self._selection_update_pending = False
        self._apply_selection_state(select_state)

    def _flush_pending_selection(self) -> None:
        """Resolve deferred drag selection before an observable boundary."""
        if self._selection_update_pending:
            self._selection_update_pending = False
            self._apply_selection_state(self._select_state)

    def _apply_selection_state(self, select_state: SelectState | None) -> None:
        """Calculate widget selections from the current pointer state."""
        if select_state is None:
            return

        if select_state.end is None:
            # Pointer hasn't yet moved
            return

        if not select_state.is_attached_to_dom:
            # Widgets may have been removed in the interim
            self._select_state = None
            return

        self.selections = select_state.selections()

    def dismiss(self, result: ScreenResultType | None = None) -> AwaitComplete:
        """Dismiss the screen, optionally with a result.

        Any callback provided in [push_screen][textual.app.App.push_screen] will be invoked with the supplied result.

        !!! warning

            Textual will raise a [`ScreenError`][textual.app.ScreenError] if you await the return value from a
            message handler on the Screen being dismissed. If you want to dismiss the current screen, you can
            call `self.dismiss()` _without_ awaiting.

        Args:
            result: The optional result to be passed to the result callback.

        """
        _rich_traceback_omit = True
        if self._result_callbacks:
            callback = self._result_callbacks[-1]
            callback(result)
        await_pop = self.app.pop_screen()

        def pre_await() -> None:
            """Called by the AwaitComplete object."""
            _rich_traceback_omit = True
            if active_message_pump.get() is self:
                from textual.app import ScreenError

                raise ScreenError(
                    "Can't await screen.dismiss() from the screen's message handler; try removing the await keyword."
                )

        await_pop.set_pre_await_callback(pre_await)

        return await_pop

    def pop_until_active(self) -> None:
        """Pop any screens on top of this one, until this screen is active.

        Raises:
            ScreenError: If this screen is not in the current mode.

        """
        from textual.app import ScreenError

        try:
            self.app._pop_to_screen(self)
        except ScreenError:
            # More specific error message
            raise ScreenError(
                f"Can't make {self} active as it is not in the current stack."
            ) from None

    async def action_dismiss(self, result: ScreenResultType | None = None) -> None:
        """A wrapper around [`dismiss`][textual.screen.Screen.dismiss] that can be called as an action.

        Args:
            result: The optional result to be passed to the result callback.
        """
        await self._flush_next_callbacks()
        self.dismiss(result)

    def can_view_entire(self, widget: Widget) -> bool:
        """Check if a given widget is fully within the current screen.

        Note: This doesn't necessarily equate to a widget being visible.
        There are other reasons why a widget may not be visible.

        Args:
            widget: A widget.

        Returns:
            `True` if the entire widget is in view, `False` if it is partially visible or not in view.
        """
        if widget not in self._compositor.visible_widgets:
            return False
        # If the widget is one that overlays the screen...
        if widget.styles.overlay == "screen":
            # ...simply check if it's within the screen's region.
            return widget.region in self.region
        # Failing that fall back to normal checking.
        return super().can_view_entire(widget)

    def can_view_partial(self, widget: Widget) -> bool:
        """Check if a given widget is at least partially within the current view.

        Args:
            widget: A widget.

        Returns:
            `True` if the any part of the widget is in view, `False` if it is completely outside of the screen.
        """
        if widget not in self._compositor.visible_widgets:
            return False
        # If the widget is one that overlays the screen...
        if widget.styles.overlay == "screen":
            # ...simply check if it's within the screen's region.
            return widget.region in self.region
        # Failing that fall back to normal checking.
        return super().can_view_partial(widget)

    def validate_title(self, title: Any) -> str | None:
        """Ensure the title is a string or `None`."""
        return None if title is None else str(title)

    def validate_sub_title(self, sub_title: Any) -> str | None:
        """Ensure the sub-title is a string or `None`."""
        return None if sub_title is None else str(sub_title)


# Retain the declaration, not the current public class attribute: replacing
# Screen.focus_chain itself must retain the replacement's selection authority.
_NATIVE_FOCUS_CHAIN = Screen.focus_chain


@rich.repr.auto
class ModalScreen(Screen[ScreenResultType]):
    """A screen with bindings that take precedence over the App's key bindings.

    The default styling of a modal screen will dim the screen underneath.
    """

    DEFAULT_CSS = """
    ModalScreen {
        layout: vertical;
        overflow-y: auto;
        background: $background 60%;
        &:ansi {
            background: transparent;                   
        }
    }
    """

    def __init__(
        self,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._modal = True


class SystemModalScreen(ModalScreen[ScreenResultType], inherit_css=False):
    """A variant of `ModalScreen` for internal use.

    This version of `ModalScreen` allows us to build system-level screens;
    the type being used to indicate that the screen should be isolated from
    the main application.

    Note:
        This screen is set to *not* inherit CSS.
    """
