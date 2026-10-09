"""Reactive declarations select access behavior before the hot read path."""

from unittest.mock import patch

import pytest

from textual.reactive import Initialize, ReactiveError, var
from textual.widget import Widget


def test_initialized_reads_do_not_probe_capabilities_or_recheck_node_identity():
    class Counter(Widget):
        value = var(7, init=False)

    node = Counter()
    assert node.value == 7
    with patch("textual.reactive.hasattr", create=True,
               side_effect=AssertionError("Reactive read rediscovered its contract")):
        assert [node.value for _ in range(100)] == [7] * 100


def test_inherited_declarations_bind_the_concrete_compute_implementation():
    class Stored(Widget):
        source = var(2, init=False)
        value = var(-1, init=False)

    class Public(Stored):
        def compute_value(self):
            return self.source * 2

    class Private(Stored):
        def _compute_value(self):
            return self.source * 3

    class Override(Public):
        def compute_value(self):
            return self.source * 5

    plain, public, private, override = Stored(), Public(), Private(), Override()
    plain.value = 19
    assert plain.value == 19
    assert (public.value, private.value, override.value) == (4, 6, 10)
    with patch("textual.reactive.hasattr", create=True,
               side_effect=AssertionError("Computed read rediscovered its contract")):
        assert (public.value, private.value, override.value) == (4, 6, 10)
    for node in (public, private, override):
        with pytest.raises(AttributeError, match="read-only"):
            node.value = 0
    # Already-declared methods still use normal Python dispatch, including
    # instance overrides; bindings must not cache a bound widget/callable.
    public.compute_value = lambda: 123
    assert public.value == 123
    assert plain.value == 19


def test_lazy_defaults_and_explicit_raw_values_preserve_native_semantics():
    initialized = []

    class Values(Widget):
        items = var(list, init=False)
        chosen = var(None, init=False)

        def make_name(self):
            initialized.append(self)
            return self.id

        name_value = var(Initialize(make_name), init=False)

    first, second = Values(id="first"), Values(id="second")
    assert first.items is not second.items
    assert first.chosen is None
    assert first.name_value == first.name_value == "first"
    assert initialized == [first]
    second.set_reactive(Values.name_value, "explicit")
    assert second.name_value == "explicit" and initialized == [first]


def test_computation_attribute_error_is_not_confused_with_uninitialized_storage():
    class BrokenCompute(Widget):
        value = var(0, init=False)

        def compute_value(self):
            raise AttributeError("inside declared compute")

    with pytest.raises(AttributeError, match="inside declared compute"):
        _ = BrokenCompute().value


@pytest.mark.parametrize("write", [False, True])
def test_missing_base_initialization_still_reports_reactive_error(write):
    class MissingInit(Widget):
        value = var(0, init=False)

        def __init__(self):
            pass

    node = MissingInit()
    with pytest.raises(ReactiveError, match="super.*__init__"):
        if write:
            node.value = 1
        else:
            _ = node.value
