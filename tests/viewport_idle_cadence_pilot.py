"""Real window demand expiry after contended native body preparation.

No provider, UI, protocol or source substitute. The actual native Markdown content locks hold a changed-width body cohort
pending; actual materialization workers, widgets and timers run.
"""

import asyncio
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from agent_comms.comms import Comms
from toad.app import ToadApp
from toad.widgets.agent_response import AgentResponse
from toad.widgets.presentation_window import MovingPreparation, StationaryPreparation
from toad.widgets.transcript_fragments import TranscriptBodyPreparation
from toad.widgets.viewport_body import MaterializingBody


async def main():
    scratch = Path(os.environ["CADENCE_SCRATCH"])
    scratch.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="native-cadence-", dir=scratch) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"),
                          XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"))
        Comms(root / "wire").messaging.initialize_private_initial_protocol()
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(110, 35)) as pilot:
            await app.selected_session.wait_content_ready()
            window = app.selected_session.conversation.window
            docs = [AgentResponse(f"## Native resource {i}\n\n" +
                                  "Selectable actual native Markdown body. " * 20,
                                  paginate=False)
                    for i in range(8)]
            await app.selected_session.conversation.contents.mount(*docs)
            manager = window.document_viewport
            lookahead = manager.lookahead
            async with asyncio.timeout(10):
                while any(not body.body_ready for body in docs) or manager._running:
                    await pilot.pause(.02)
            window.focus(scroll_visible=False)
            await pilot.press("end")
            async with asyncio.timeout(8):
                while not any(body in app.screen._compositor.visible_widgets for body in docs):
                    await pilot.pause(.01)
            window.release_anchor()
            await manager.suspend_source()
            short = [AgentResponse(f"## Foreground {i}\n\nActual native body.", paginate=False)
                     for i in range(6)]
            await app.selected_session.conversation.contents.mount(*short)
            await pilot.pause(.1)
            window.scroll_end(animate=False, immediate=True)
            await pilot.pause(.1)
            visible = app.screen._compositor.visible_widgets
            cohort = tuple(body for body in short if body in visible)
            assert len(cohort) >= 2
            for body in cohort:
                assert await body.retire_body()
            # Changed width makes retained rows insufficient; the original
            # Markdown lock is acquired by actual native reconstruction.
            await pilot.resize_terminal(90, 35)
            await pilot.pause(.1)
            assert all(not body.body_ready for body in cohort)
            for body in cohort:
                await body.lock.acquire()
            manager.resume_source()
            try:
                async with asyncio.timeout(8):
                    while any(not isinstance(body._body_measurement, MaterializingBody)
                              for body in cohort):
                        await pilot.pause(.01)
                assert all(body._body_measurement.worker.is_running for body in cohort)
                pending_workers = [body._body_measurement.worker.name for body in cohort]
                await asyncio.sleep(.5)
                assert all(not body.body_ready for body in cohort)
            finally:
                for body in reversed(cohort):
                    body.lock.release()
            async with asyncio.timeout(8):
                while manager._running or not manager.visible_bodies_ready:
                    await pilot.pause(.01)
            assert all(body.body_ready for body in cohort)
            assert not window.history_lock.locked()
            assert window.history_layout_ready is None
            foreground = cohort[0]
            slow_delivery = lookahead.delivery_seconds
            assert slow_delivery > lookahead.budget.scroll_idle_seconds
            # Source-page warm-up is background work, whether its source is
            # already prepared or cold. It must not replace the latency of the
            # actual foreground restoration above.
            await manager.suspend_source()
            background = docs[0]
            assert background not in app.screen._compositor.visible_widgets
            preparation = TranscriptBodyPreparation(
                app.render_processes, app.native_ansi_color, app.current_theme.dark,
            )
            await preparation.dispatch(background.TRANSCRIPT_EVENT(background.source))
            await manager._restore_bodies((background,), foreground, manager.lookahead.demand)
            assert background.body_ready
            background_delivery = lookahead.delivery_seconds
            (scratch / "receipt.json").write_text(json.dumps({
                "foreground_delivery_seconds": slow_delivery,
                "delivery_after_background_seconds": background_delivery,
                "foreground_measured": slow_delivery > lookahead.budget.scroll_idle_seconds,
                "changed_width_cohort": len(cohort),
                "original_pending_workers": pending_workers,
                "background_preserved_horizon": background_delivery == slow_delivery,
                "boundary": "actual source UI/widget/worker journey; not installed physical capture",
            }, indent=2) + "\n")
            assert background_delivery == slow_delivery, "Warm-up overwrote foreground delivery horizon"
            manager.resume_source()
            window.release_anchor()
            window.focus(scroll_visible=False)
            await pilot.press("pageup")
            assert isinstance(lookahead.demand, MovingPreparation)
            await pilot.pause(lookahead.budget.scroll_idle_seconds + .05)
            assert isinstance(lookahead.demand, StationaryPreparation)
            assert lookahead.travel_rows == 0
            await pilot.press("pagedown")
            assert lookahead.travel_rows > 0
            await pilot.press("pageup")
            assert lookahead.travel_rows < 0
            await pilot.press("end")
            await pilot.pause(lookahead.budget.scroll_idle_seconds + .05)
            assert lookahead.travel_rows == 0
            assert app._exception is None
            print(json.dumps({"foreground_cohort": len(cohort),
                              "actual_body_delivery_seconds": slow_delivery,
                              "configured_idle_seconds": lookahead.budget.scroll_idle_seconds,
                              "boundary": "actual headless framework resource/timer journey; not physical capture",
                              "phases": ["contended_restore", "pageup", "idle", "pagedown", "reverse", "end", "idle"]}))


if __name__ == "__main__":
    asyncio.run(main())
