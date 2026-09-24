"""Renderer warm-up starts after display and never holds typing or navigation."""

import asyncio
import os
from pathlib import Path
import tempfile
from typing import TypeVar

from runtime_fixture import ToadApp
from toad.render_backend import Renderer
from toad.render_tasks import RenderTask

ResultT = TypeVar("ResultT")


class GateRenderer(Renderer):
    def __init__(self, displayed: asyncio.Event) -> None:
        self.displayed = displayed
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.finished = asyncio.Event()
        self.calls = 0
        self.closed = False

    async def warm_up(self, *, project: Path, ansi: bool, dark: bool) -> None:
        assert self.displayed.is_set(), "Warm-up started before the first completed display"
        self.calls += 1
        self.started.set()
        try:
            await self.release.wait()
        finally:
            self.finished.set()

    async def submit(self, task: RenderTask[ResultT]) -> ResultT:
        raise AssertionError("Fixture must not submit user rendering work")

    async def aclose(self) -> None:
        self.closed = True


class FrameApp(ToadApp):
    def __init__(self, displayed: asyncio.Event, **kwargs):
        self.displayed = displayed
        super().__init__(**kwargs)

    def _display(self, screen, renderable):
        result = super()._display(screen, renderable)
        if renderable is not None and not self._batch_count and screen is self.screen:
            self.displayed.set()
        return result


async def main():
    with tempfile.TemporaryDirectory(prefix="renderer-warmup-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        displayed = asyncio.Event()
        renderer = GateRenderer(displayed)
        app = FrameApp(displayed, project_dir=directory, renderer=renderer)
        async with app.run_test(size=(110, 35)) as pilot:
            await asyncio.wait_for(renderer.started.wait(), 3)
            await pilot.pause()
            first = app.current_mode
            prompt = app.screen.conversation.prompt
            prompt.focus()
            await pilot.press("h", "i")
            assert prompt.text == "hi"
            other = await asyncio.wait_for(app.new_session_screen(app.get_main_screen), 3)
            await asyncio.wait_for(app.switch_mode(first), 3)
            await pilot.pause()
            assert other.mode_name != first and prompt.text == "hi"
            assert renderer.calls == 1 and not renderer.release.is_set()
            assert app._exception is None
        assert renderer.closed and renderer.finished.is_set()
        await asyncio.get_running_loop().shutdown_default_executor()
    print("warm-up: after display, once per app; typing/navigation/drafts work while blocked; shutdown drains")


if __name__ == "__main__":
    asyncio.run(main())
