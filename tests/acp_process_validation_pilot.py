"""The official ACP validator stays off the UI heap and publishes in wire order."""

import asyncio
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

from runtime_fixture import ToadApp
from toad.acp.agent import Agent
from toad.acp.messages import RejectedSessionUpdate, ToolCall, TurnStarted, TurnSettled


async def main():
    assert "acp.schema" not in sys.modules
    with TemporaryDirectory(prefix="toad-process-validation-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        app = ToadApp(project_dir=str(root))
        async with app.run_test() as pilot:
            await pilot.pause()
            view = app.screen.conversation
            agent = Agent(root, {"name": "Fixture", "identity": "fixture", "run_command": {"*": "true"}}, "fixture")
            agent._message_target = view
            observed, logged = [], []
            agent.post_message = observed.append
            agent.log = logged.append

            async def deliver(payload, session="fixture"):
                return await agent.server.call({"jsonrpc": "2.0", "method": "session/update",
                    "params": {"sessionId": session, "update": payload}})

            original = {"sessionUpdate": "tool_call", "toolCallId": "one", "title": "Inspect",
                        "custom": {"nested": [1, 2]}}
            assert agent.server.requires_ordered_dispatch({"method": "session/update"})
            assert not agent.server.requires_ordered_dispatch({"method": "terminal/create"})
            assert await deliver(original) is None
            assert len(observed) == 1 and isinstance(observed[0], ToolCall)
            assert observed[0].tool_call is original
            assert "acp.schema" not in sys.modules, "SDK validator graph entered the UI heap"
            await deliver({"sessionUpdate": "usage_update", "used": "10", "size": "100"})
            assert isinstance(observed[-1], RejectedSessionUpdate) and logged

            # The off-process boundary must carry the immutable wire session
            # into current-main lifecycle/queue handlers, not substitute the
            # attachment's current identity after validation.
            started = {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": ""},
                       "_meta": {"agentComms": {"turnStarted": True, "turnId": "ordered-turn"}}}
            before = len(observed)
            await deliver(started, session="foreign-session")
            assert len(observed) == before
            await deliver(started)
            assert isinstance(observed[-1], TurnStarted)
            assert observed[-1].agent is agent and observed[-1].session_id == "fixture"
            await deliver({"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": ""},
                           "_meta": {"agentComms": {"turnSettled": True, "turnId": "ordered-turn"}}})
            assert isinstance(observed[-1], TurnSettled)
            assert observed[-1].session_id == "fixture"
            assert "acp.schema" not in sys.modules

            # Hold validation delivery. A second notification must not overtake
            # it, and retiring the target invalidates both before publication.
            entered, release = asyncio.Event(), asyncio.Event()
            submit = app.render_processes.submit
            admissions = []

            async def held(task):
                admissions.append(task)
                result = await submit(task)
                entered.set()
                await release.wait()
                return result

            before = len(observed)
            with patch.object(app.render_processes, "submit", held):
                first = asyncio.create_task(deliver(original))
                await asyncio.wait_for(entered.wait(), 10)
                second = asyncio.create_task(deliver(original))
                await asyncio.sleep(.02)
                assert len(admissions) == 1
                view.prompt.focus()
                await pilot.press("x")
                assert view.prompt.text == "x"
                agent._message_target = None
                release.set()
                await asyncio.gather(first, second)
            assert len(observed) == before
            assert "acp.schema" not in sys.modules
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("ACP process validation: SDK isolated, raw payload identity preserved, strict rejection/order/retirement verified")


if __name__ == "__main__":
    asyncio.run(main())
