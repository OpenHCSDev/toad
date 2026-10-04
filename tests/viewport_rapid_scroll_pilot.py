"""Rapid reverse/forward scrolling keeps painted source and end navigation coupled."""

import asyncio
import os
import psutil
from pathlib import Path
from tempfile import TemporaryDirectory
from dataclasses import replace

from runtime_fixture import ToadApp
from toad.widgets.agent_response import AgentResponse


class FrameApp(ToadApp):
    observed = None

    def _display(self, screen, renderable):
        if self.observed is not None and renderable is not None and not self._batch_count and screen is self.screen:
            end, window, frames = self.observed
            frames.append((window.follows_tail, end in screen._compositor.visible_widgets,
                           end.body_ready, window.scroll_y, window.max_scroll_y,
                           window.document_viewport.lookahead.admission(
                               window.document_viewport.budget, window.size.height)))
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
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"),
                          TOAD_TEST_ATTEMPT=f"workspace-rapid-{os.getpid()}", XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        app = FrameApp(project_dir=str(root))
        async with app.run_test(size=(100, 34)) as pilot:
            await pilot.pause()
            print("RAPID_WORKSPACE_READY", flush=True)
            view = app.selected_session.conversation
            editor = view.prompt.prompt_text_area
            editor.insert("retained rapid-scroll draft")
            editor.history.checkpoint()
            editor.insert(" with undo")
            document, edit_history = editor.document, editor.history
            docs = [AgentResponse(f"## Record {index}\n\n" + "measured source text " * 25)
                    for index in range(48)]
            docs[-1] = AgentResponse("## LAST SOURCE\n\n" + "last record " * 15 + "\n\nTAIL-RECORD-END")
            await view.contents.mount(*docs)
            window = view.window
            # This journey must exercise body retirement even when the ordinary
            # warmed fixture fits PR202's retained-resource budget. Configure
            # actual resource pressure; do not synthesize dormant body state.
            window.document_viewport.budget = replace(
                window.document_viewport.budget, minimum_widgets=100, widgets_per_row=0,
            )
            window.anchor()
            await settled(view, pilot)
            print("RAPID_SOURCE_READY", window.max_scroll_y, flush=True)
            assert window.max_scroll_y > 100
            end = docs[-1]
            assert end.body_ready
            for round_index in range(3):
                print("RAPID_NAVIGATION_ROUND", round_index, flush=True)
                window.release_anchor()
                window.scroll_to(y=0, animate=False, immediate=True)
                await settled(view, pilot)
                for _ in range(18):
                    await pilot.press("pagedown")
                await pilot.press("end")
                await settled(view, pilot)
                assert window.follows_tail and window.scroll_y == window.max_scroll_y, (window.follows_tail, window.scroll_y, window.max_scroll_y)
                assert end.body_ready and end in app.screen._compositor.visible_widgets
                region = window.scrollable_content_region
                painted = "\n".join(strip.crop(region.x, region.right).text
                                    for strip in app.screen._compositor.render_strips()[region.y:region.bottom])
                assert "TAIL-RECORD-END" in painted
                assert app._exception is None
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
            print("RAPID_COLD_TAIL_READY", flush=True)
            frames = []
            app.observed = end, window, frames
            window.focus()
            await pilot.press("end")
            await settled(view, pilot)
            app.observed = None
            assert frames and all(y <= maximum for _, _, _, y, maximum, _ in frames)
            print("END_PREPARATION_ADMISSION", [frame[-1] for frame in frames], flush=True)
            assert not any(follow and visible and not ready for follow, visible, ready, *_ in frames), frames
            assert window.follows_tail and window.scroll_y == window.max_scroll_y, (window.follows_tail, window.scroll_y, window.max_scroll_y)
            assert end.body_ready and end in app.screen._compositor.visible_widgets
            await pilot.pause(.3)
            viewport = window.document_viewport
            assert viewport._settle_timer is None
            assert viewport.lookahead.travel_rows == 0
            # Idle retains its measured baseline runway. Four bodies is an
            # admission floor, not the row-derived runway's fixed size.
            assert viewport.lookahead.admission(viewport.budget, window.size.height) <= viewport.budget.item_limit(0)
            assert not viewport._running and not viewport._pending
            before = psutil.Process().cpu_times()
            await pilot.pause(.3)
            after = psutil.Process().cpu_times()
            print("RAPID_IDLE_RESOURCES", {
                "cpu_seconds": (after.user + after.system) - (before.user + before.system),
                "rss_bytes": psutil.Process().memory_info().rss,
                "prepared_bytes": app.preparation.retained_bytes,
                "pending_work": len(app.preparation._pending),
                "warm_bodies": len(viewport._warm),
            }, flush=True)
            assert app.preparation.retained_bytes <= app.preparation.max_bytes
            assert len(app.preparation._pending) <= app.preparation.max_pending
            assert editor.document is document and editor.history is edit_history
            editor.undo()
            assert editor.text == "retained rapid-scroll draft"
        await asyncio.get_running_loop().shutdown_default_executor()
    print("rapid viewport: PageDown/End and cold-tail return pass native visible-body paint")


if __name__ == "__main__":
    asyncio.run(main())
