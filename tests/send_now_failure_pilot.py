"""A rejected ACP Send now request clears its pending indicator, not its queue."""

import asyncio
import os
import tempfile
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

from toad import jsonrpc
from toad.acp.agent import Agent
from toad.app import ToadApp


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-send-now-failure-", dir="/var/tmp") as raw:
        root = Path(raw)
        os.environ.update(
            XDG_CONFIG_HOME=str(root / "config"), XDG_DATA_HOME=str(root / "data"),
            XDG_STATE_HOME=str(root / "state"), AGENT_COMMS_ROOT=str(root / "wire"),
        )
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            view = app.screen.conversation
            agent = Agent(root, {"name": "Rejected request test", "run_command": {"*": "false"}, "identity": "rejected"}, "test-session")
            view.set_reactive(type(view).agent, agent)
            view.queued_prompts = ["keep this instruction"]
            view.sending_queued_prompt = "keep this instruction"

            class FailedRequest:
                async def wait(self):
                    raise jsonrpc.JSONRPCError("Send boundary rejected")

            with patch.object(agent, "request", return_value=nullcontext()), patch(
                "toad.acp.agent.api.session_prompt", return_value=FailedRequest()
            ):
                await view.send_queued_now().wait()
            assert view.sending_queued_prompt == ""
            assert view.queued_prompts == ["keep this instruction"]
            assert app._exception is None
    print("send-now failure: pending indicator cleared and instruction retained")


if __name__ == "__main__":
    asyncio.run(main())
