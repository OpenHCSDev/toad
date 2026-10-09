from functools import partial

import pytest

from textual._callback import count_parameters


def test_functions() -> None:
    """Test count parameters of functions."""

    def foo(): ...
    def bar(a): ...
    def baz(a, b): ...

    # repeat to allow for caching
    for _ in range(3):
        assert count_parameters(foo) == 0
        assert count_parameters(bar) == 1
        assert count_parameters(baz) == 2


def test_methods() -> None:
    """Test count parameters of methods."""

    class Foo:
        def foo(self): ...
        def bar(self, a): ...
        def baz(self, a, b): ...

    foo = Foo()

    # repeat to allow for caching
    for _ in range(3):
        assert count_parameters(foo.foo) == 0
        assert count_parameters(foo.bar) == 1
        assert count_parameters(foo.baz) == 2


def test_partials() -> None:
    """Test count parameters of partials."""

    class Foo:
        def method(self, a, b, c, d): ...

    foo = Foo()

    partial0 = partial(foo.method)
    partial1 = partial(foo.method, 10)
    partial2 = partial(foo.method, b=10, c=20)

    for _ in range(3):
        assert count_parameters(partial0) == 4
        assert count_parameters(partial0) == 4

        assert count_parameters(partial1) == 3
        assert count_parameters(partial1) == 3

        assert count_parameters(partial2) == 2
        assert count_parameters(partial2) == 2


@pytest.mark.parametrize("bound_first", [True, False])
def test_binding_order_preserves_original_function_arity(bound_first) -> None:
    class Owner:
        def callback(self, old, value): ...

    owner = Owner()
    first, second = ((owner.callback, Owner.callback) if bound_first
                     else (Owner.callback, owner.callback))
    assert count_parameters(first) == (2 if bound_first else 3)
    assert count_parameters(second) == (3 if bound_first else 2)
    assert count_parameters(partial(owner.callback, 1)) == 1
    assert count_parameters(partial(Owner.callback, owner, 1)) == 1
    assert count_parameters(Owner.callback) == 3
    assert count_parameters(owner.callback) == 2


def test_uncacheable_callable_retains_signature_contract() -> None:
    assert count_parameters(len) == 1
    assert count_parameters(partial(len)) == 1


async def test_watchers_and_invocation_share_original_binding() -> None:
    from textual._callback import invoke
    from textual.app import App
    from textual.reactive import reactive
    from textual.widget import Widget

    observations = []

    class Observed(Widget):
        value = reactive(0)

        def watch_value(self, old, value):
            observations.append((old, value))

    # An unbound API consumer must not change native watcher dispatch.
    assert count_parameters(Observed.watch_value) == 3
    owner = Observed()
    app = App()
    async with app.run_test() as pilot:
        await app.mount(owner)
        await pilot.pause()
        owner.value = 5
        await pilot.pause()
        assert observations[-1] == (0, 5)
        # Bound watcher discovery must not truncate later unbound invocation.
        await invoke(Observed.watch_value, owner, 7, 9)
        assert observations[-1] == (7, 9)
        await invoke(partial(owner.watch_value, 11), 13)
        assert observations[-1] == (11, 13)
