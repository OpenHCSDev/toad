"""

This module contains the `Reactive` class which implements [reactivity](/guide/reactivity/).
"""

from __future__ import annotations

from functools import partial
from inspect import isawaitable, iscoroutine
from operator import methodcaller
from weakref import WeakKeyDictionary
from typing import (
    TYPE_CHECKING,
    Any,
    Awaitable,
    Callable,
    ClassVar,
    Generic,
    Type,
    TypeVar,
    cast,
    overload,
)

import rich.repr

from textual import events
from textual._callback import count_parameters
from textual._types import (
    MessageTarget,
    WatchCallbackBothValuesType,
    WatchCallbackNewValueType,
    WatchCallbackNoArgsType,
    WatchCallbackType,
)

if TYPE_CHECKING:
    from textual.dom import DOMNode

    Reactable = DOMNode

ReactiveType = TypeVar("ReactiveType")
ReactableType = TypeVar("ReactableType", bound="DOMNode")


class _Mutated:
    """A wrapper to indicate a value was mutated."""

    def __init__(self, value: Any) -> None:
        self.value = value


class ReactiveError(Exception):
    """Base class for reactive errors."""


class TooManyComputesError(ReactiveError):
    """Raised when an attribute has public and private compute methods."""


class Initialize(Generic[ReactiveType]):
    """Initialize a reactive by calling a method parent object.

    Example:
        ```python
            class InitializeApp(App):

                def get_names(self) -> list[str]:
                    return ["foo", "bar", "baz"]

                # The `names` property will call `get_names` to get its default when first referenced.
                names = reactive(Initialize(get_names))
        ```

    """

    def __init__(self, callback: Callable[[ReactableType], ReactiveType]) -> None:
        self.callback = callback

    def __call__(self, obj: ReactableType) -> ReactiveType:
        return self.callback(obj)


class WatcherCallback(events.Callback):
    """Own a watcher's already-created result through deferred delivery."""

    def __init__(self, obj: Reactable, awaitable: Awaitable[object]) -> None:
        self.obj = obj
        self.awaitable = awaitable
        super().__init__(self._await_result)

    async def _await_result(self) -> None:
        await self.awaitable
        # Watcher may have changed the state, so run compute again.
        self.obj.post_message(
            events.Callback(callback=partial(Reactive._compute, self.obj))
        )

    def _discard(self) -> None:
        # A freshly returned coroutine belongs to this deferred delivery.
        # Tasks / Futures have an independent execution owner; do not cancel
        # them merely because this callback was never admitted.
        if iscoroutine(self.awaitable):
            self.awaitable.close()

    def __rich_repr__(self) -> rich.repr.Result:
        yield "obj", self.obj
        yield "awaitable", self.awaitable


class _StoredReactiveAccess:
    """Class-owned value access; no widget or bound callback is retained here."""

    __slots__ = ()

    def get(self, reactive: Reactive[ReactiveType], obj: Reactable) -> ReactiveType:
        try:
            return obj.__dict__[reactive.internal_name]
        except KeyError:
            reactive._initialize_reactive(obj, reactive.name)
            return obj.__dict__[reactive.internal_name]

    def initial_value(self, reactive: Reactive[ReactiveType], obj: Reactable) -> ReactiveType:
        return reactive._default_value(obj)

    def require_writable(self, reactive: Reactive, obj: Reactable) -> None:
        """Stored declarations accept writes."""

    def compute(self, reactive: Reactive, obj: Reactable) -> None:
        """Stored declarations have no derived value to recompute."""


class _ComputedReactiveAccess(_StoredReactiveAccess):
    __slots__ = ("_compute_value",)

    def __init__(self, compute_name: str) -> None:
        # Compile the declared method call, retaining normal Python dispatch
        # for overrides without storing a bound widget or probing capabilities.
        self._compute_value = methodcaller(compute_name)

    def get(self, reactive: Reactive[ReactiveType], obj: Reactable) -> ReactiveType:
        super().get(reactive, obj)
        self.compute(reactive, obj)
        return obj.__dict__[reactive.internal_name]

    def initial_value(self, reactive: Reactive[ReactiveType], obj: Reactable) -> ReactiveType:
        return self._compute_value(obj) if reactive._init else reactive._default_value(obj)

    def require_writable(self, reactive: Reactive, obj: Reactable) -> None:
        raise AttributeError(
            f"Can't set {obj}.{reactive.name!r}; reactive attributes with a compute method are read-only"
        )

    def compute(self, reactive: Reactive, obj: Reactable) -> None:
        current = obj.__dict__.get(reactive.internal_name, reactive._default)
        value = self._compute_value(obj)
        obj.__dict__[reactive.internal_name] = value
        if value != current:
            reactive._check_watchers(obj, reactive.name, current)


_STORED_REACTIVE_ACCESS = _StoredReactiveAccess()


def invoke_watcher(
    watcher_object: Reactable,
    watch_function: WatchCallbackType,
    old_value: object,
    value: object,
) -> None:
    """Invoke a watch function.

    Args:
        watcher_object: The object watching for the changes.
        watch_function: A watch function, which may be sync or async.
        old_value: The old value of the attribute.
        value: The new value of the attribute.
    """
    _rich_traceback_omit = True

    param_count = count_parameters(watch_function)

    with watcher_object._context():
        if param_count == 2:
            watch_result = cast(WatchCallbackBothValuesType, watch_function)(
                old_value, value
            )
        elif param_count == 1:
            watch_result = cast(WatchCallbackNewValueType, watch_function)(value)
        else:
            watch_result = cast(WatchCallbackNoArgsType, watch_function)()
        if isawaitable(watch_result):
            # Result is awaitable, so we need to await it within an async context
            watcher_object.call_next(WatcherCallback(watcher_object, watch_result))


@rich.repr.auto
class Reactive(Generic[ReactiveType]):
    """Reactive descriptor.

    Args:
        default: A default value or callable that returns a default.
        layout: Perform a layout on change.
        repaint: Perform a repaint on change.
        init: Call watchers on initialize (post mount).
        always_update: Call watchers even when the new value equals the old value.
        compute: Run compute methods when attribute is changed.
        recompose: Compose the widget again when the attribute changes.
        bindings: Refresh bindings when the reactive changes.
        toggle_class: An optional TCSS classname(s) to toggle based on the truthiness of the value.
    """

    _reactives: ClassVar[dict[str, object]] = {}

    def __init__(
        self,
        default: ReactiveType | Callable[[], ReactiveType] | Initialize[ReactiveType],
        *,
        layout: bool = False,
        repaint: bool = True,
        init: bool = False,
        always_update: bool = False,
        compute: bool = True,
        recompose: bool = False,
        bindings: bool = False,
        toggle_class: str | None = None,
    ) -> None:
        self._default = default
        self._layout = layout
        self._repaint = repaint
        self._init = init
        self._always_update = always_update
        self._run_compute = compute
        self._recompose = recompose
        self._bindings = bindings
        self._toggle_class = toggle_class
        self._owner: Type[MessageTarget] | None = None
        self.name: str

    def __rich_repr__(self) -> rich.repr.Result:
        yield None, self._default
        yield "layout", self._layout, False
        yield "repaint", self._repaint, True
        yield "init", self._init, False
        yield "always_update", self._always_update, False
        yield "compute", self._run_compute, True
        yield "recompose", self._recompose, False
        yield "bindings", self._bindings, False
        yield "name", getattr(self, "name", None), None

    @classmethod
    def _clear_watchers(cls, obj: Reactable) -> None:
        """Clear any watchers on a given object.

        Args:
            obj: A reactive object.
        """
        try:
            getattr(obj, "__watchers").clear()
        except AttributeError:
            pass

    @classmethod
    def _clear_watch_subscriptions(cls, node: Reactable) -> None:
        """Release this subscriber from publishers, including quiet publishers.

        Publishers retain callbacks strongly for delivery. The subscriber owns
        their lifetime; its reverse index must not itself retain publishers.
        """
        sources = getattr(node, "_reactive_watch_sources", None)
        if sources is None:
            return
        node._reactive_watch_sources = None
        for source, attributes in tuple(sources.items()):
            watchers = getattr(source, "__watchers", {})
            for attribute in attributes:
                remaining = [(subscriber, callback) for subscriber, callback in watchers.get(attribute, ())
                             if subscriber is not node]
                # Replace rather than mutate a list which may be delivering a
                # change. Other subscribers keep their order and registration.
                if remaining:
                    watchers[attribute] = remaining
                else:
                    watchers.pop(attribute, None)

    @property
    def owner(self) -> Type[MessageTarget]:
        """The owner (class) where the reactive was declared."""
        assert self._owner is not None
        return self._owner

    def _bind_access(self, compute_methods: frozenset[str]) -> _StoredReactiveAccess:
        """Resolve the concrete class's declaration once, including inherited vars."""
        private_name = f"_compute_{self.name}"
        public_name = f"compute_{self.name}"
        if private_name in compute_methods:
            return _ComputedReactiveAccess(private_name)
        if public_name in compute_methods:
            return _ComputedReactiveAccess(public_name)
        return _STORED_REACTIVE_ACCESS

    def _default_value(self, obj: Reactable) -> ReactiveType:
        default = self._default
        if isinstance(default, Initialize):
            return default(obj)
        return default() if callable(default) else default

    def _initialize_reactive(self, obj: Reactable, name: str) -> None:
        """Initialized a reactive attribute on an object.

        Args:
            obj: An object with reactive attributes.
            name: Name of attribute.
        """
        _rich_traceback_omit = True

        internal_name = self.internal_name
        if internal_name in obj.__dict__:
            # Attribute already has a value
            return
        if "_id" not in obj.__dict__:
            raise ReactiveError(
                f"Node is missing data; Check you are calling super().__init__(...) in the {obj.__class__.__name__}() constructor, before accessing reactives."
            )

        default = obj._reactive_accessors[name].initial_value(self, obj)
        obj.__dict__[internal_name] = default
        if (toggle_class := self._toggle_class) is not None:
            obj.set_class(bool(default), *toggle_class.split())
        if self._init:
            self._check_watchers(obj, name, default)

    @classmethod
    def _initialize_object(cls, obj: Reactable) -> None:
        """Set defaults and call any watchers / computes for the first time.

        Args:
            obj: An object with Reactive descriptors
        """
        _rich_traceback_omit = True
        for name, reactive in obj._reactives.items():
            reactive._initialize_reactive(obj, name)

    @classmethod
    def _reset_object(cls, obj: object) -> None:
        """Reset reactive structures on object (to avoid reference cycles).

        Args:
            obj: A reactive object.
        """
        getattr(obj, "__watchers", {}).clear()
        getattr(obj, "__computes", []).clear()

    def __set_name__(self, owner: Type[MessageTarget], name: str) -> None:
        # Check for compute method
        self._owner = owner
        public_compute = f"compute_{name}"
        private_compute = f"_compute_{name}"
        compute_name = (
            private_compute if hasattr(owner, private_compute) else public_compute
        )
        if hasattr(owner, compute_name):
            # Compute methods are stored in a list called `__computes`
            try:
                computes = getattr(owner, "__computes")
            except AttributeError:
                computes = []
                setattr(owner, "__computes", computes)
            computes.append(name)

        # The name of the attribute
        self.name = name
        # The internal name where the attribute's value is stored
        self.internal_name = f"_reactive_{name}"
        self.compute_name = compute_name
        default = self._default
        setattr(owner, f"_default_{name}", default)

    if TYPE_CHECKING:

        @overload
        def __get__(
            self: Reactive[ReactiveType],
            obj: ReactableType,
            obj_type: type[ReactableType],
        ) -> ReactiveType: ...

        @overload
        def __get__(
            self: Reactive[ReactiveType], obj: None, obj_type: type[ReactableType]
        ) -> Reactive[ReactiveType]: ...

    def __get__(
        self: Reactive[ReactiveType],
        obj: Reactable | None,
        obj_type: type[ReactableType],
    ) -> Reactive[ReactiveType] | ReactiveType:
        _rich_traceback_omit = True
        if obj is None:
            # obj is None means we are invoking the descriptor via the class, and not the instance
            return self
        return obj._reactive_accessors[self.name].get(self, obj)

    def _set(
        self, obj: Reactable, value: ReactiveType, always: bool = False,
        *, layout: bool | None = None,
    ) -> None:
        _rich_traceback_omit = True

        if isinstance(value, _Mutated):
            value = value.value
            always = True

        self._initialize_reactive(obj, self.name)

        obj._reactive_accessors[self.name].require_writable(self, obj)

        name = self.name
        current_value = getattr(obj, name)
        # Check for private and public validate functions.
        private_validate_function = getattr(obj, f"_validate_{name}", None)
        if callable(private_validate_function):
            value = private_validate_function(value)
        public_validate_function = getattr(obj, f"validate_{name}", None)
        if callable(public_validate_function):
            value = public_validate_function(value)

        # Toggle the classes using the value's truthiness
        if (toggle_class := self._toggle_class) is not None:
            obj.set_class(bool(value), *toggle_class.split())

        # If the value has changed, or this is the first time setting the value
        if always or self._always_update or current_value != value:
            # Store the internal value
            setattr(obj, self.internal_name, value)

            # Check all watchers
            self._check_watchers(obj, name, current_value)

            if self._run_compute:
                self._compute(obj)

            if self._bindings:
                obj.refresh_bindings()

            # Refresh according to descriptor flags
            request_layout = self._layout if layout is None else layout
            if request_layout or self._repaint or self._recompose:
                obj.refresh(
                    repaint=self._repaint,
                    layout=request_layout,
                    recompose=self._recompose,
                )

    def __set__(self, obj: Reactable, value: ReactiveType) -> None:
        _rich_traceback_omit = True

        self._set(obj, value)

    @classmethod
    def _check_watchers(cls, obj: Reactable, name: str, old_value: Any) -> None:
        """Check watchers, and call watch methods / computes

        Args:
            obj: The reactable object.
            name: Attribute name.
            old_value: The old (previous) value of the attribute.
        """
        _rich_traceback_omit = True
        # Get the current value.
        internal_name = f"_reactive_{name}"
        value = getattr(obj, internal_name)

        private_watch_function = getattr(obj, f"_watch_{name}", None)
        if callable(private_watch_function):
            invoke_watcher(obj, private_watch_function, old_value, value)

        public_watch_function = getattr(obj, f"watch_{name}", None)
        if callable(public_watch_function):
            invoke_watcher(obj, public_watch_function, old_value, value)

        # Process "global" watchers
        watchers: list[tuple[Reactable, WatchCallbackType]]
        watchers = getattr(obj, "__watchers", {}).get(name, [])
        # Remove any watchers for reactables that have since closed
        if watchers:
            watchers[:] = [
                (reactable, callback)
                for reactable, callback in watchers
                if not reactable._closing
            ]
            for reactable, callback in watchers:
                if reactable._closing or reactable._closed:
                    continue
                with reactable.prevent(*obj._prevent_message_types_stack[-1]):
                    invoke_watcher(reactable, callback, old_value, value)

    @classmethod
    def _compute(cls, obj: Reactable) -> None:
        """Invoke all computes.

        Args:
            obj: Reactable object.
        """
        _rich_traceback_guard = True
        for compute in obj._reactives.keys() & obj._computes:
            obj._reactive_accessors[compute].compute(obj._reactives[compute], obj)


class reactive(Reactive[ReactiveType]):
    """Create a reactive attribute.

    Args:
        default: A default value or callable that returns a default.
        layout: Perform a layout on change.
        repaint: Perform a repaint on change.
        init: Call watchers on initialize (post mount).
        always_update: Call watchers even when the new value equals the old value.
        recompose: Compose the widget again when the attribute changes.
        bindings: Refresh bindings when the reactive changes.
        toggle_class: An optional TCSS classname(s) to toggle based on the truthiness of the value.
    """

    def __init__(
        self,
        default: ReactiveType | Callable[[], ReactiveType] | Initialize[ReactiveType],
        *,
        layout: bool = False,
        repaint: bool = True,
        init: bool = True,
        always_update: bool = False,
        recompose: bool = False,
        bindings: bool = False,
        toggle_class: str | None = None,
    ) -> None:
        super().__init__(
            default,
            layout=layout,
            repaint=repaint,
            init=init,
            always_update=always_update,
            recompose=recompose,
            bindings=bindings,
            toggle_class=toggle_class,
        )


class var(Reactive[ReactiveType]):
    """Create a reactive attribute (with no auto-refresh).

    Args:
        default: A default value or callable that returns a default.
        init: Call watchers on initialize (post mount).
        always_update: Call watchers even when the new value equals the old value.
        bindings: Refresh bindings when the reactive changes.
        toggle_class: An optional TCSS classname(s) to toggle based on the truthiness of the value.
    """

    def __init__(
        self,
        default: ReactiveType | Callable[[], ReactiveType] | Initialize[ReactiveType],
        init: bool = True,
        always_update: bool = False,
        bindings: bool = False,
        toggle_class: str | None = None,
    ) -> None:
        super().__init__(
            default,
            layout=False,
            repaint=False,
            init=init,
            always_update=always_update,
            bindings=bindings,
            toggle_class=toggle_class,
        )


def _watch(
    node: DOMNode,
    obj: Reactable,
    attribute_name: str,
    callback: WatchCallbackType,
    *,
    init: bool = True,
) -> None:
    """Watch a reactive variable on an object.

    Args:
        node: The node that created the watcher.
        obj: The parent object.
        attribute_name: The attribute to watch.
        callback: A callable to call when the attribute changes.
        init: True to call watcher initialization.
    """
    if node._closing or node._closed:
        return
    if not hasattr(obj, "__watchers"):
        setattr(obj, "__watchers", {})
    watchers: dict[str, list[tuple[Reactable, WatchCallbackType]]]
    watchers = getattr(obj, "__watchers")
    watcher_list = watchers.setdefault(attribute_name, [])
    if any(callback == callback_from_list for _, callback_from_list in watcher_list):
        return
    if init:
        current_value = getattr(obj, attribute_name, None)
        invoke_watcher(obj, callback, current_value, current_value)
    if node._closing or node._closed:
        return
    watcher_list.append((node, callback))
    sources = getattr(node, "_reactive_watch_sources", None)
    if sources is None:
        node._reactive_watch_sources = sources = WeakKeyDictionary()
    sources.setdefault(obj, set()).add(attribute_name)
