"""
Tests for scrolling animations, which are considered a basic animation.
(An animation that also plays on the level BASIC.)
"""

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Label


class TallApp(App[None]):
    def compose(self) -> ComposeResult:
        with VerticalScroll():
            for _ in range(100):
                yield Label()


async def test_scrolling_animates_on_full() -> None:
    app = TallApp()
    app.animation_level = "full"

    async with app.run_test() as pilot:
        vertical_scroll = app.query_one(VerticalScroll)
        animator = app.animator
        # Freeze time at 0 before triggering the animation.
        animator._get_time = lambda *_: 0
        vertical_scroll.scroll_end(duration=10000)
        await pilot.pause()
        # Freeze time after the animation start and before animation end.
        animator._get_time = lambda *_: 0.01
        # Move to the next frame.
        animator()
        assert animator.is_being_animated(vertical_scroll, "scroll_y")


async def test_scrolling_animates_on_basic() -> None:
    app = TallApp()
    app.animation_level = "basic"

    async with app.run_test() as pilot:
        vertical_scroll = app.query_one(VerticalScroll)
        animator = app.animator
        # Freeze time at 0 before triggering the animation.
        animator._get_time = lambda *_: 0
        vertical_scroll.scroll_end(duration=10000)
        await pilot.pause()
        # Freeze time after the animation start and before animation end.
        animator._get_time = lambda *_: 0.01
        # Move to the next frame.
        animator()
        assert animator.is_being_animated(vertical_scroll, "scroll_y")


async def test_scrolling_does_not_animate_on_none() -> None:
    app = TallApp()
    app.animation_level = "none"

    async with app.run_test() as pilot:
        vertical_scroll = app.query_one(VerticalScroll)
        animator = app.animator
        # Freeze time at 0 before triggering the animation.
        animator._get_time = lambda *_: 0
        vertical_scroll.scroll_end(duration=10000)
        await pilot.pause()
        # Freeze time after the animation start and before animation end.
        animator._get_time = lambda *_: 0.01
        # Move to the next frame.
        animator()
        assert not animator.is_being_animated(vertical_scroll, "scroll_y")


async def test_scroll_replacement_preserves_current_position_and_other_axis() -> None:
    """New intent replaces its curve without painting the former destination."""
    app = TallApp()
    async with app.run_test() as pilot:
        window = app.query_one(VerticalScroll)
        animator = app.animator
        animator._get_time = lambda: 0
        window.scroll_to(y=60, duration=10, easing="linear", immediate=True)
        animator._get_time = lambda: 5
        animator()
        position = window.scroll_y
        assert 0 < position < 60

        # A deferred operation must not finish the previous destination while
        # it is waiting for the screen's existing after-refresh delivery.
        destination = min(80, window.max_scroll_y)
        window.scroll_to(y=destination, duration=10, easing="linear")
        assert window.scroll_y == position
        await pilot.pause()
        curve = animator._animations[(id(window), "scroll_y")]
        assert window.scroll_y == position
        assert curve.start_value == position
        assert curve.end_value == destination

        # Reversal to the current position ends the old curve instead of
        # silently leaving it to run toward a destination no longer requested.
        window.scroll_to(y=position, duration=10, immediate=True)
        assert window.scroll_y == position
        assert not animator.is_being_animated(window, "scroll_y")

        animator.animate(window, "scroll_x", 10, duration=10)
        other_axis = animator._animations[(id(window), "scroll_x")]
        window.scroll_to(y=80, duration=10, immediate=True)
        window.scroll_to(y=position, animate=False, immediate=True)
        assert window.scroll_y == position
        assert animator._animations[(id(window), "scroll_x")] is other_axis
        assert not animator.is_being_animated(window, "scroll_y")

        animator.animate(window, "scroll_y", 60, delay=10, duration=10)
        scheduled = animator._scheduled[(id(window), "scroll_y")]
        window.scroll_to(y=position, animate=False, immediate=True)
        assert not animator.is_being_animated(window, "scroll_y")
        assert scheduled._callback is None
