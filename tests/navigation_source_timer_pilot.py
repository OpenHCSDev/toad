"""A clicked tab must outrank the departing view's stale layout timer."""

import asyncio
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from runtime_fixture import ToadApp
from toad.widgets.agent_response import AgentResponse


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-navigation-timer-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(100, 35)) as pilot:
            await pilot.pause()
            first_mode = app.current_mode
            first = app.screen
            await first.conversation.contents.mount(AgentResponse("Saved text that stays visible"))
            second = await app.new_session_screen(app.get_main_screen)
            second_mode = second.mode_name
            await app.switch_mode(first_mode)
            await pilot.pause()
            async with app._mode_switch_lock:
                with patch.object(first, "_refresh_layout", wraps=first._refresh_layout) as layout:
                    pending = app.switch_mode(second_mode)
                    assert app._pending_mode_switch == second_mode
                    first.refresh(layout=True)
                    assert first._layout_required
                    first._on_timer_update()
                    layout.assert_not_called()
                    assert first._layout_required, "Departing screen lost a real invalidation"
            await asyncio.wait_for(pending, 10)
            assert app.current_mode == second_mode
            assert app._pending_mode_switch is None
            await app.switch_mode(first_mode)
            await pilot.pause()
            assert "Saved text that stays visible" in first.conversation.contents.query_one(
                AgentResponse).source
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("mode switch: departing full-layout timer deferred; returning view reflows with its saved content")


if __name__ == "__main__":
    asyncio.run(main())
