"""A toolkit-neutral observable field descriptor.

Replaces Textual's `var[T]` and PyQt's `Signal`/`Property` pairs with a plain descriptor
both backends drive. The Textual side bridges each `ObservedField` to a corresponding
Textual `var` where its reactive-watcher semantics are actually needed; the Qt side reads
and writes the field directly and forwards change notifications to Qt signals as the
widget wants.

Not a reactive framework. One value, a get/set, change callbacks. Everything that needs
scheduling, deduplication or dependency tracking composes it with its own machinery.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Generic, TypeVar


T = TypeVar("T")


class ObservedField(Generic[T]):
    """One instance attribute whose writes fire registered change callbacks.

    Used as a class-level descriptor. The default is shared by instances that never
    assign; a first assignment or callback registration stores per-instance state.
    """

    __slots__ = ("_default", "_name")

    def __init__(self, default: T) -> None:
        self._default = default
        self._name = ""

    def __set_name__(self, owner: type, name: str) -> None:
        self._name = f"_observed_{name}"

    def __get__(self, instance: object | None, owner: type | None = None) -> T:
        if instance is None:
            return self  # type: ignore[return-value]
        state: _State[T] = getattr(instance, self._name, None) or _State(self._default)
        return state.value

    def __set__(self, instance: object, value: T) -> None:
        state: _State[T] | None = getattr(instance, self._name, None)
        if state is None:
            state = _State(self._default)
            object.__setattr__(instance, self._name, state)
        before = state.value
        state.value = value
        if before != value:
            for callback in tuple(state.callbacks):
                callback(before, value)

    def watch(self, instance: object, callback: Callable[[T, T], None]) -> Callable[[], None]:
        """Register a change callback on `instance`; returns an unregister handle."""
        state: _State[T] | None = getattr(instance, self._name, None)
        if state is None:
            state = _State(self._default)
            object.__setattr__(instance, self._name, state)
        state.callbacks.append(callback)
        return lambda: state.callbacks.remove(callback) if callback in state.callbacks else None


class _State(Generic[T]):
    __slots__ = ("value", "callbacks")

    def __init__(self, value: T) -> None:
        self.value = value
        self.callbacks: list[Callable[[T, T], None]] = []
