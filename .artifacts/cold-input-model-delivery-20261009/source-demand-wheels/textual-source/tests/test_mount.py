"""Regression test for https://github.com/Textualize/textual/issues/2914

Make sure that calls to render only happen after a widget being mounted.
"""

import asyncio
from unittest.mock import Mock

import pytest

from textual.app import App
from textual.widget import AwaitMount, Widget


async def test_concurrent_composition_keeps_nested_declarations_private():
    from textual.containers import Horizontal, Vertical
    from textual.widgets import Static

    class Nested(Widget):
        def compose(self):
            with Vertical(id=f"{self.id}-outer"):
                with Horizontal(id=f"{self.id}-inner"):
                    yield Static("first", id=f"{self.id}-first")
                    yield Static("second", id=f"{self.id}-second")

    app = App()
    async with app.run_test():
        left, right = Nested(id="left"), Nested(id="right")
        await app.mount(left, right)
        for root in (left, right):
            outer = root.query_one(f"#{root.id}-outer")
            inner = root.query_one(f"#{root.id}-inner")
            assert list(root.children) == [outer]
            assert list(outer.children) == [inner]
            assert [child.id for child in inner.children] == [
                f"{root.id}-first", f"{root.id}-second"
            ]
        assert app._compose_stacks == [] and app._composed == []


async def test_cancelled_private_composition_closes_its_original_context():
    from textual.compose import compose, compose_async
    from textual.containers import Vertical
    from textual.widgets import Static

    entered = asyncio.Event()
    closed = []

    def declaration():
        try:
            with Vertical(id="private"):
                entered.set()
                yield Static("first")
                yield Static("second")
        finally:
            closed.append(True)

    app = App()
    async with app.run_test():
        collecting = asyncio.create_task(compose_async(app, declaration()))
        await entered.wait()
        collecting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await collecting
        assert closed == [True]
        assert app._compose_stacks == [] and app._composed == []
        assert not app.query("#private")
        # The synchronous public entry still uses the same validation / scope.
        complete = compose(app, iter([Static("complete")]))
        await app.mount_all(complete)
        assert list(app.screen.children) == complete


class W(Widget):
    def render(self):
        return self.renderable

    async def on_mount(self):
        await asyncio.sleep(0.1)
        self.renderable = "1234"


async def test_render_only_after_mount():
    """Regression test for https://github.com/Textualize/textual/issues/2914"""
    app = App()
    async with app.run_test() as pilot:
        app.mount(W())
        app.mount(W())
        await pilot.pause()


async def test_mount_completion_is_shared_by_explicit_and_scheduled_awaiters():
    parent = Mock(spec=Widget)
    parent._closing = parent._closed = parent._pruning = False
    children = [Widget(), Widget()]
    mounted = AwaitMount(parent, children)
    explicit = asyncio.create_task(mounted())
    scheduled = asyncio.create_task(mounted())
    await asyncio.sleep(0)
    children[0]._mounted_event.set()
    await asyncio.sleep(0)
    assert not explicit.done() and not scheduled.done()
    children[1]._mounted_event.set()
    await asyncio.gather(explicit, scheduled)
    await mounted
    parent.refresh.assert_called_once_with(layout=True)
    parent.app._update_mouse_over.assert_called_once_with(parent.screen)


async def test_cancelling_one_mount_awaiter_does_not_cancel_completion():
    parent = Mock(spec=Widget)
    parent._closing = parent._closed = parent._pruning = False
    child = Widget()
    mounted = AwaitMount(parent, [child])
    first = asyncio.create_task(mounted())
    second = asyncio.create_task(mounted())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    await asyncio.sleep(0)
    waiters = [task for task in asyncio.all_tasks() if task.get_name() == "await mount"]
    assert len(waiters) <= 1, "A cancelled mount waiter left duplicate child waits"
    assert not second.done()
    child._mounted_event.set()
    await asyncio.wait_for(second, 1)
    parent.refresh.assert_called_once_with(layout=True)


async def test_eager_composition_observes_completed_registration_and_styles():
    """Compose must not run inside a caller's unfinished mount / cover setup."""
    from textual.color import Color

    observed = []

    class Probe(Widget):
        def _post_register(self, app):
            super()._post_register(app)
            self.registration_complete = True

        def compose(self):
            assert self.registration_complete
            assert self._task is asyncio.current_task()
            assert self.styles.color == Color.parse("red")
            if self.id != "cover":
                assert all(
                    self.app.query_one(f"#{name}").styles.color == Color.parse("red")
                    for name in ("first", "second")
                )
            observed.append(self.id)
            return []

    class StartupApp(App):
        CSS = "Probe { color: red; }"

    loop = asyncio.get_running_loop()
    previous_factory = loop.get_task_factory()
    app = StartupApp()
    try:
        async with app.run_test() as pilot:
            loop.set_task_factory(asyncio.eager_task_factory)
            first, second = Probe(id="first"), Probe(id="second")
            await app.screen.mount(first, second)
            first._cover(Probe(id="cover"))
            await pilot.pause()
            assert observed == ["first", "second", "cover"]
            first._uncover()
            await first.remove()
            await second.remove()
    finally:
        loop.set_task_factory(previous_factory)


async def test_initial_notifications_observe_complete_tree_styles_and_css_sources():
    """Initial resource acquisition follows the complete registration's styles."""
    from textual.color import Color

    observed = []

    class Probe(Widget):
        def notify_style_update(self):
            super().notify_style_update()
            if self.id and not self.is_mounted:
                assert self.rich_style.color == Color.parse("red").rich_color
                assert self.app.query_one("#left").rich_style.italic
                observed.append(self.id)

    class LaterDeclaration(Probe):
        SCOPED_CSS = False
        DEFAULT_CSS = "#left { text-style: italic; }"

    class RegistrationApp(App):
        CSS = "#parent-a, #parent-b { color: red; }"

    app = RegistrationApp()
    async with app.run_test():
        left, right, last = Probe(id="left"), Probe(id="right"), Probe(id="last")
        first = Probe(id="parent-a")
        second = LaterDeclaration(id="parent-b")
        first._add_children(left, right)
        second._add_children(last)
        await app.mount(first, second)
        assert observed == ["left", "right", "last", "parent-a", "parent-b"]
        assert list(app.screen.children) == [first, second]
        assert list(first.children) == [left, right]


async def test_unawaited_mount_does_not_hold_parent_wheel_delivery():
    """Real driver input can use the existing viewport during child startup."""
    from textual import events
    from textual.containers import VerticalScroll
    from textual.widgets import Static

    entered, release, delivered = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class AcquiringChild(Static):
        async def on_mount(self):
            entered.set()
            await release.wait()

    class MountingApp(App):
        def compose(self):
            with VerticalScroll(id="viewport"):
                yield Static("Existing body\n" * 40, id="body")

        async def on_event(self, event):
            ingress = isinstance(event, events.MouseScrollDown) and not event.is_forwarded
            result = await super().on_event(event)
            if ingress:
                delivered.set()
            return result

    app = MountingApp()
    async with app.run_test(size=(40, 12)) as pilot:
        viewport = app.query_one("#viewport", VerticalScroll)
        child = AcquiringChild("New body")
        receipts = []

        def acquire():
            receipts.append(viewport.mount(child))

        viewport.call_later(acquire)
        try:
            await asyncio.wait_for(entered.wait(), 1)
            assert not receipts[0].is_done
            point = app.query_one("#body").region.offset
            app._driver.process_message(events.MouseScrollDown(None, point.x + 1, point.y + 1,
                                                               0, 0, 0, False, False, False))
            await asyncio.wait_for(delivered.wait(), 1)
            assert viewport.scroll_y > 0
            assert not child.is_mounted
        finally:
            release.set()
        await receipts[0]
        await pilot.pause()
        assert child.is_mounted
        assert child in app.screen._compositor.widgets


async def test_completion_admission_applies_to_each_distinct_operation():
    """Shared admission runs without borrowing another operation's constructor."""
    from textual.await_complete import AwaitComplete

    admissions = []
    app = App()
    async with app.run_test():
        child = Widget()
        mounting = app.mount(child)
        mounting.set_pre_await_callback(lambda: admissions.append("mount"))
        assert await mounting is None
        removing = child.remove()
        removing.set_pre_await_callback(lambda: admissions.append("remove"))
        assert await removing is None
        completed = AwaitComplete.nothing()
        completed.set_pre_await_callback(lambda: admissions.append("group"))
        assert await completed is None
        assert mounting.is_done and removing.is_done and completed.is_done
        # Explicit and scheduled receipt consumers each run admission. The
        # completion itself still publishes once, regardless of waiter count.
        assert admissions[0] == "mount"
        assert "remove" in admissions
        assert admissions[-1] == "group"
