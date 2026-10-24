"""Textual-facing: the animation clock's timer returns to the event loop between ticks, so hidden fades whose interval shrinks every tick cannot freeze the app."""

import asyncio

from textual.app import App
from ui_theme.effects import CURSOR_BLINK, NEW_MESSAGE, NEW_TEXT

from toad.textual_colours import ThemedApp


class Target:
    def __init__(self, animation_visible: bool) -> None:
        self.animation_visible = animation_visible

    def repaint(self) -> None:
        pass


class ClockApp(ThemedApp, App):
    pass


async def test_hidden_fades_tick_once_per_loop_turn():
    app = ClockApp()
    async with app.run_test():
        # `App.run` installs this factory; `run_test` does not.
        asyncio.get_running_loop().set_task_factory(asyncio.eager_task_factory)
        clock = app.colours.clock
        tick = clock.tick
        depth = deepest = 0

        def counted() -> None:
            nonlocal depth, deepest
            depth += 1
            deepest = max(deepest, depth)
            try:
                tick()
            finally:
                depth -= 1

        clock.tick = counted
        clock.start(CURSOR_BLINK, Target(True))
        hidden = Target(False)
        for index in range(3):
            clock.start((NEW_TEXT, NEW_MESSAGE)[index % 2], hidden)
            await asyncio.sleep(0.013 * index)
        lag = 0.0
        loop = asyncio.get_running_loop()
        for _ in range(20):
            started = loop.time()
            await asyncio.sleep(0.02)
            lag = max(lag, loop.time() - started)
    assert deepest == 1
    assert lag < 0.2
