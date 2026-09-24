"""Post-compaction zero usage is unknown, not an empty model context."""

import asyncio
import os
import tempfile
from pathlib import Path

from runtime_fixture import ToadApp
from toad.acp.agent import Agent


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-context-usage-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(100, 35)) as pilot:
            await pilot.pause()
            view = app.screen.conversation
            agent = Agent(root, {"name": "Fixture", "identity": "fixture",
                                 "short_name": "fixture", "run_command": {"*": "true"},
                                 "protocol": "acp"}, "fixture")
            agent._message_target = view
            agent.rpc_session_update("fixture", {"sessionUpdate": "usage_update", "used": 120000,
                                                 "size": 272000})
            await pilot.pause()
            assert "120.0K" in str(view.status)
            agent.rpc_session_update("fixture", {"sessionUpdate": "usage_update", "used": 0,
                                                 "size": 272000})
            await pilot.pause()
            assert agent._context_usage is None
            assert "Context estimate unavailable" in str(view.status)
            assert "0.0K" not in str(view.status)
            agent.rpc_session_update("fixture", {"sessionUpdate": "usage_update", "used": 27000,
                                                 "size": 272000})
            await pilot.pause()
            assert "27.0K" in str(view.status)
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("context usage: unknown zero after compaction; next valid estimate restores percentage")


if __name__ == "__main__":
    asyncio.run(main())
