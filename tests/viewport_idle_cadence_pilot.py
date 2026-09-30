"""Real window demand expiry after contended native body preparation.

No provider, UI, protocol or source substitute. The existing history lock
introduces a bounded resource wait; actual native widgets and timers run.
"""

import asyncio
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from runtime_fixture import ToadApp
from toad.widgets.agent_response import AgentResponse
from toad.widgets.presentation_window import MovingPreparation, StationaryPreparation


async def main():
    scratch = Path(os.environ["CADENCE_SCRATCH"])
    scratch.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="native-cadence-", dir=scratch) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"),
                          XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(110, 35)) as pilot:
            await pilot.pause()
            window = app.selected_session.conversation.window
            docs = [AgentResponse(f"## Native resource {i}\n\n" +
                                  "Selectable actual native Markdown body. " * 100)
                    for i in range(8)]
            await app.selected_session.conversation.contents.mount(*docs)
            await pilot.pause(.2)
            manager = window.document_viewport
            lookahead = manager.lookahead
            # Contention is on the real resource owner, not a replacement body
            # or a clock mock. Delivery measures the full actual restore wait.
            await window.history_lock.acquire()
            restore = asyncio.create_task(manager._restore_body(docs[-1], docs[-1]))
            try:
                await asyncio.sleep(.5)
            finally:
                window.history_lock.release()
            await asyncio.wait_for(restore, 8)
            slow_delivery = lookahead.delivery_seconds
            assert slow_delivery > lookahead.budget.scroll_idle_seconds
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
            print(json.dumps({"actual_body_delivery_seconds": slow_delivery,
                              "configured_idle_seconds": lookahead.budget.scroll_idle_seconds,
                              "boundary": "actual headless framework resource/timer journey; not physical capture",
                              "phases": ["contended_restore", "pageup", "idle", "pagedown", "reverse", "end", "idle"]}))


if __name__ == "__main__":
    asyncio.run(main())
