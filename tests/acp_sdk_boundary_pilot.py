"""ACP v1 SDK acceptance, raw extension retention and visible rejection pilot."""

import asyncio
import os
import tempfile
from pathlib import Path

from pydantic import ValidationError
from runtime_fixture import ToadApp

from toad.acp.agent import Agent
from toad.acp.messages import ToolCall
from toad.acp.sdk_boundary import validate_session_update
from toad.widgets.note import Note


def verify_valid_updates_preserve_identity() -> None:
    updates = [
        {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "hi",
            "displayExtension": "keep"}, "_meta": {"agentComms": {"route": {"from": "a"}}}},
        {"sessionUpdate": "tool_call", "toolCallId": "t1", "title": "Inspect",
            "customToolField": {"nested": [1, 2]}},
        {"sessionUpdate": "tool_call_update", "toolCallId": "t1", "status": "completed"},
        {"sessionUpdate": "usage_update", "used": 100, "size": 1000},
        {"sessionUpdate": "session_info_update", "title": "Session"},
    ]
    for update in updates:
        before = repr(update)
        assert validate_session_update("fixture", update) is update
        assert repr(update) == before

    for update in (
        {"sessionUpdate": "agent_message_chunk", "content": {"type": "text"}},
        {"sessionUpdate": "tool_call", "toolCallId": "t1"},
        {"sessionUpdate": "future_update", "content": {"type": "text", "text": "hi"}},
        ["not an ACP notification"],
    ):
        try:
            validate_session_update("fixture", update)
        except ValidationError:
            pass
        else:
            raise AssertionError(f"SDK accepted malformed update {update!r}")


async def verify_dispatch_and_visible_rejection(root: Path) -> None:
    app = ToadApp(project_dir=str(root))
    async with app.run_test(size=(90, 30)) as pilot:
        await pilot.pause()
        view = app.screen.conversation
        agent = Agent(root, {"name": "Fixture", "identity": "fixture",
                             "short_name": "fixture", "run_command": {"*": "true"},
                             "protocol": "acp"}, "fixture")
        agent._message_target = view
        recorded = []
        agent.log = recorded.append

        raw = {"sessionUpdate": "tool_call", "toolCallId": "t1", "title": "Inspect",
               "customToolField": {"nested": [1, 2]}}
        intercepted = []
        agent.post_message = intercepted.append
        agent.rpc_session_update("fixture", raw)
        assert len(intercepted) == 1 and isinstance(intercepted[0], ToolCall)
        assert intercepted[0].tool_call is raw

        agent.post_message = view.post_message
        malformed = {"sessionUpdate": "agent_message_chunk", "content": {"type": "text"}}
        response = await agent.server.call({"jsonrpc": "2.0", "method": "session/update",
                                            "params": {"sessionId": "fixture", "update": malformed}})
        assert response is None  # Invalid notifications are contained at the boundary.
        await pilot.pause()
        notes = [widget for widget in view.contents.children
                 if isinstance(widget, Note) and "Invalid ACP update rejected" in widget.render().plain]
        assert len(notes) == 1, "Rejected updates need a visible conversation marker"
        assert recorded and repr(malformed) in recorded[-1] and "validation=" in recorded[-1]
        assert app._exception is None
    await asyncio.get_running_loop().shutdown_default_executor()


async def main() -> None:
    verify_valid_updates_preserve_identity()
    with tempfile.TemporaryDirectory(prefix="toad-acp-sdk-phase1-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"),
                          XDG_DATA_HOME=str(root / "data"),
                          XDG_STATE_HOME=str(root / "state"),
                          AGENT_COMMS_ROOT=str(root / "wire"))
        await verify_dispatch_and_visible_rejection(root)
    print("ACP SDK v1: raw extensions preserved; invalid wire update logged and shown")


if __name__ == "__main__":
    asyncio.run(main())
