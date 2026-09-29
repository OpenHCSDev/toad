"""Rapid reverse/forward scrolling keeps painted source and end navigation coupled."""

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from runtime_fixture import ToadApp
from toad.widgets.agent_response import AgentResponse


class FrameApp(ToadApp):
    observed = None

    def _display(self, screen, renderable):
        if self.observed is not None and renderable is not None and not self._batch_count and screen is self.screen:
            end, window, frames = self.observed
            frames.append((window.follows_tail, end in screen._compositor.visible_widgets,
                           end.body_ready, window.scroll_y, window.max_scroll_y))
        super()._display(screen, renderable)


async def settled(view, pilot):
    async with asyncio.timeout(12):
        while True:
            await pilot.pause(.02)
            viewport = view.window.document_viewport
            if not viewport._running and viewport.visible_bodies_ready:
                return


async def main():
    with TemporaryDirectory(prefix="toad-rapid-history-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        app = FrameApp(project_dir=str(root))
        async with app.run_test(size=(100, 34)) as pilot:
            await pilot.pause()
            view = app.screen.conversation
            docs = [AgentResponse(f"## Record {index}\n\n" + "measured source text " * 25)
                    for index in range(48)]
            docs[-1] = AgentResponse("## LAST SOURCE\n\n" + "last record " * 15 + "\n\nTAIL-RECORD-END")
            await view.contents.mount(*docs)
            window = view.window
            window.anchor()
            deadline = asyncio.get_running_loop().time() + 12
            while window.max_scroll_y <= 100 and asyncio.get_running_loop().time() < deadline:
                await pilot.pause(.02)
            assert window.max_scroll_y > 100, (
                window.max_scroll_y, len(view.contents.children), len(window.document_viewport.owners),
                len(app.screen._compositor.visible_widgets), app._exception,
                [(doc.body_ready, doc.body_dormant, doc.loading, doc.display, doc.outer_size.height,
                  len(doc.children), doc._body_measurement, doc.styles.height) for doc in docs[:3]],
            )
            await settled(view, pilot)
            end = docs[-1]
            assert end.body_ready
            original = AgentResponse.restore_body
            loads = 0

            async def counted(body):
                nonlocal loads
                if body is end:
                    loads += 1
                return await original(body)

            with patch.object(AgentResponse, "restore_body", counted):
                for _ in range(3):
                    window.release_anchor()
                    window.scroll_to(y=0, animate=False, immediate=True)
                    await settled(view, pilot)
                    for _ in range(18):
                        await pilot.press("pagedown")
                    await pilot.press("end")
                    await settled(view, pilot)
                    assert window.follows_tail and window.scroll_y == window.max_scroll_y
                    assert end.body_ready and end in app.screen._compositor.visible_widgets
                    painted = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
                    assert "TAIL-RECORD-END" in painted, (window.scroll_y, window.max_scroll_y)
                    assert app._exception is None
            assert loads <= 1, f"Repeated up/down rebuilt the same recent tail {loads} times"
            middle = docs[20]
            loads = 0

            async def counted_middle(body):
                nonlocal loads
                if body is middle:
                    loads += 1
                return await original(body)

            with patch.object(AgentResponse, "restore_body", counted_middle):
                for _ in range(3):
                    window.release_anchor()
                    window.scroll_to_widget(middle, animate=False, immediate=True)
                    await settled(view, pilot)
                    assert middle.body_ready
                    for index in (15, 11, 7, 5):
                        window.scroll_to_widget(docs[index], animate=False, immediate=True)
                        await settled(view, pilot)
                assert loads <= 1, f"Returning to a recent non-tail document reloaded it {loads} times"
            for index in range(40, -1, -4):
                window.scroll_to_widget(docs[index], animate=False, immediate=True)
                await settled(view, pilot)
            assert end.body_dormant, (
                "Fixture must exercise an unloaded source tail", window.scroll_y,
                window.max_scroll_y, len(window.document_viewport._warm),
                [index for index, body in enumerate(docs) if body in window.document_viewport.protected()],
                [index for index, body in enumerate(docs)
                 if any(key() is body for key in window.document_viewport._warm)],
                end._body_measurement, end in app.screen._compositor.visible_widgets,
            )
            entered, release = asyncio.Event(), asyncio.Event()
            frames = []
            app.observed = end, window, frames

            async def held_restore(body):
                if body is end:
                    entered.set()
                    await release.wait()
                return await original(body)

            with patch.object(AgentResponse, "restore_body", held_restore):
                window.focus()
                ending = asyncio.create_task(pilot.press("end"))
                try:
                    async with asyncio.timeout(5):
                        await entered.wait()
                    assert not any(follow and (not visible or not ready)
                                   for follow, visible, ready, *_ in frames), frames
                finally:
                    release.set()
                await asyncio.wait_for(ending, 5)
            await settled(view, pilot)
            app.observed = None
            assert frames and all(y <= maximum for _, _, _, y, maximum in frames)
            assert window.follows_tail and window.scroll_y == window.max_scroll_y
            assert end.body_ready and end in app.screen._compositor.visible_widgets
        await asyncio.get_running_loop().shutdown_default_executor()
    print("rapid viewport: Page Down/End show source tail without repeated body rebuilds")


if __name__ == "__main__":
    asyncio.run(main())
