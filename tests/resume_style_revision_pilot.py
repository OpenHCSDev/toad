"""Unchanged CSS reparses never restyle old tabs; real CSS changes still do."""

import asyncio
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from runtime_fixture import ToadApp


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-resume-style-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(100, 35)) as pilot:
            await pilot.pause()
            first_mode = app.current_mode
            first = app.screen
            second = (await app.new_session_screen(app.get_main_screen)).mode_name
            await app.switch_mode(first_mode)
            await pilot.pause()
            assert first._resume_style is not None
            rules_before = id(app.stylesheet.rules_map)
            app.stylesheet.reparse()
            assert id(app.stylesheet.rules_map) != rules_before
            with patch.object(first, "update_node_styles", wraps=first.update_node_styles) as styled:
                await app.switch_mode(second)
                await app.switch_mode(first_mode)
                await pilot.pause()
                styled.assert_not_called()

            app.stylesheet.add_source(
                "AgentResponse { color: #ffaa22; }",
                read_from=("benchmark", "Changed.DEFAULT_CSS"), is_default_css=True,
            )
            app.stylesheet.parse()
            with patch.object(first, "update_node_styles", wraps=first.update_node_styles) as styled:
                await app.switch_mode(second)
                await app.switch_mode(first_mode)
                await pilot.pause()
                assert styled.call_count > 0, "Source changes must restyle existing tabs"
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("resume styles: identical reparse skips full restyle; changed source refreshes old tab")


if __name__ == "__main__":
    asyncio.run(main())
