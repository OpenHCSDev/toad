"""Measure tab removal and the remaining selected view without a provider."""

import asyncio
import json
import os
from pathlib import Path
import tempfile
import time
from unittest.mock import patch

from runtime_fixture import ToadApp
from toad.widgets.agent_response import AgentResponse


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-close-timing-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        app = ToadApp(project_dir=str(root))
        results = []
        async with app.run_test(size=(110, 35)) as pilot:
            await pilot.pause()
            base = app.current_mode
            for index in range(4):
                mode = (await app.new_session_screen(app.get_main_screen)).mode_name
                await app.screen.conversation.contents.mount(*[
                    AgentResponse(f"Response {i}\n\n" + "long paragraphs.\n\n" * 10)
                    for i in range(14)
                ])
                await pilot.pause()
                observed = []
                original_remove = app.remove_mode
                start = time.perf_counter()

                async def measured_remove(selected):
                    observed.append(("before_remove", (time.perf_counter() - start) * 1000))
                    assert not any(tab.mode_name == mode for tab in app.open_tabs), (
                        "Closed tab remained visible during screen teardown", mode,
                    )
                    result = await original_remove(selected)
                    observed.append(("after_remove", (time.perf_counter() - start) * 1000))
                    return result

                with patch.object(app, "remove_mode", measured_remove):
                    await app.close_session_mode(mode)
                observed.append(("closed", (time.perf_counter() - start) * 1000))
                assert app.current_mode == base and mode not in app._open_tab_order
                results.append({"round": index, "stages_ms": [(name, round(ms, 2)) for name, ms in observed]})
            print(json.dumps({"boundary": "headless close handler; not terminal pixels", "samples": results}, indent=2))
        await asyncio.get_running_loop().shutdown_default_executor()


if __name__ == "__main__":
    asyncio.run(main())
