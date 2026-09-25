"""Typed ACP compaction updates reach mounted Toad without inventing usage."""

import asyncio
import os
import tempfile
from pathlib import Path

from runtime_fixture import ToadApp

from toad.acp.agent import Agent
from toad.acp.messages import TurnStarted
from toad.widgets.agent_response import AgentResponse
from toad.widgets.conversation import TurnActivity


def compaction_packet(phase, *, summary="", will_retry=False):
    return {
        "sessionUpdate": "agent_message_chunk",
        "content": {"type": "text", "text": "Core-only status; not an ordinary assistant reply"},
        "_meta": {"agentComms": {"compaction": {
            "phase": phase,
            "status": {"start": "running", "end": "completed", "abort": "aborted"}[phase],
            "reason": "threshold",
            "contextState": "unknown",
            "contextUsed": None,
            "willRetry": will_retry,
            **({"summary": summary} if summary else {}),
        }}},
    }


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-midturn-compact-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"),
                          XDG_DATA_HOME=str(root / "data"),
                          XDG_STATE_HOME=str(root / "state"),
                          AGENT_COMMS_ROOT=str(root / "wire"))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(100, 34)) as pilot:
            await pilot.pause()
            view = app.screen.conversation
            agent = Agent(root, {"name": "Fixture", "identity": "fixture",
                                 "short_name": "fixture", "run_command": {"*": "true"},
                                 "protocol": "acp"}, "fixture")
            agent._message_target = view
            view.post_message(TurnStarted("active-turn", None, "working", "Thinking"))
            agent.rpc_session_update("fixture", {
                "sessionUpdate": "usage_update", "used": 120000, "size": 272000,
            })
            await pilot.pause()
            assert "120.0K" in str(view.status)

            agent.rpc_session_update("fixture", compaction_packet("start"))
            await pilot.pause()
            assert agent._context_usage is None
            assert "Context estimate unavailable" in str(view.status)
            assert "0.0K" not in str(view.status) and "120.0K" not in str(view.status)
            assert "Compacting context" in view.query_one(TurnActivity).render().plain
            assert view.busy_count == 1

            summary = "AUTO-COMPACTION-PRESERVED-DECISIONS"
            agent.rpc_session_update("fixture", compaction_packet(
                "end", summary=summary, will_retry=True))
            await pilot.pause()
            notices = [item for item in view.contents.children
                       if isinstance(item, AgentResponse) and summary in item.source]
            assert len(notices) == 1
            assert "Context compacted" in notices[0].source
            assert "Core-only status" not in notices[0].source
            assert view.busy_count == 1 and "Context estimate unavailable" in str(view.status)

            # A second, aborted attempt must not masquerade as another success.
            agent.rpc_session_update("fixture", compaction_packet("start"))
            agent.rpc_session_update("fixture", compaction_packet("abort"))
            await pilot.pause()
            aborted = [item for item in view.contents.children
                       if isinstance(item, AgentResponse) and "Compaction aborted" in item.source]
            assert len(aborted) == 1 and view.busy_count == 1
            assert "Compaction did not complete" in aborted[0].source
            assert "Context estimate unavailable" in str(view.status)
            agent.rpc_session_update("fixture", {
                "sessionUpdate": "usage_update", "used": 27000, "size": 272000,
            })
            await pilot.pause()
            assert "27.0K" in str(view.status)

            # A normal message with similar text does not clear typed usage.
            agent.rpc_session_update("fixture", {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": "compaction_start is plain text"},
            })
            await pilot.pause()
            assert "27.0K" in str(view.status) and app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("typed mid-turn compaction: busy lifecycle, one summary, unknown then fresh usage")


if __name__ == "__main__":
    asyncio.run(main())
