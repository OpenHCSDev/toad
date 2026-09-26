"""Provider-free receipt/lifecycle negatives through the real message queue."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from runtime_fixture import ToadApp
from toad.acp.agent import Agent
from toad.acp import messages
from toad.screens.main import MainScreen
from toad.widgets.note import Note

INPUT = "a" * 32
AGENT_DATA = {
    "name": "Fixture", "identity": "fixture", "short_name": "fixture",
    "run_command": {"*": "true"}, "protocol": "acp",
}


def receipt(**overrides: object) -> dict:
    base = {
        "version": 1, "source": "pi-mcp-client", "inputId": INPUT,
        "state": "running", "lifetime": "turn",
        "servers": [{"id": "fixture", "scope": "project", "state": "ready",
                     "calls": "confirm", "tools": 2, "resources": 1, "prompts": 0}],
    }
    base.update(overrides)
    return base


def chunk(value: object, input_id: object = INPUT, turn: object = None,
          text: object = "") -> dict:
    envelope = {"mcpClient": value, "inputId": input_id, "turnId": turn}
    return {"sessionUpdate": "agent_message_chunk",
            "content": {"type": "text", "text": text},
            "_meta": {"agentComms": envelope}}


def turn_signal(kind: str, turn: str) -> dict:
    return {"sessionUpdate": "user_message_chunk", "content": {"type": "text", "text": ""},
            "_meta": {"agentComms": {kind: True, "turnId": turn}}}


def notes(view) -> list[str]:
    return [str(widget.render()) for widget in view.contents.children
            if isinstance(widget, Note) and "MCP live" in str(widget.render())]


async def exercise_boundaries(agent, view, pilot) -> None:
    """Each negative is drained before checking; no dedupe-masked assertions."""
    session = agent.session_id

    async def send(update, session_id=session):
        agent.rpc_session_update(session_id, update)
        await pilot.pause()

    await send(chunk(receipt(), turn="turn-1"))
    assert not notes(view)
    await send(turn_signal("turnStarted", "turn-1"))
    assert agent._active_turn_id == view._managed_turn_id == "turn-1"
    for update in [
        chunk(receipt()), chunk(receipt(), input_id="forged", turn="turn-1"),
        chunk({"version": 2}, turn="turn-1"),
        chunk(receipt(version=True), turn="turn-1"),
        chunk(receipt(servers=[{"id": "x"}]), turn="turn-1"),
        chunk(receipt(inputId="b" * 32), turn="turn-1"),
        chunk(receipt(state="idle"), turn="turn-1"),
        chunk(receipt(), turn="turn-1", text="hello"),
        chunk(receipt(), turn="wrong"),
    ]:
        await send(update)
        assert not notes(view), update
    # Foreign lifecycle MUST NOT reach the conversation, even with its current ID.
    for update in [turn_signal("turnStarted", "foreign"),
                   turn_signal("turnSettled", "turn-1"),
                   chunk(receipt(), turn="turn-1")]:
        await send(update, "foreign-session")
        assert agent._active_turn_id == view._managed_turn_id == "turn-1"
        assert not notes(view)
    await send(chunk(receipt(), turn="turn-1"))
    rendered = notes(view)
    assert len(rendered) == 1 and "not a grant" in rendered[0]
    await send(chunk(receipt(), turn="turn-1"))
    assert notes(view) == rendered
    await send(turn_signal("turnSettled", "turn-1"))
    assert agent._active_turn_id is view._managed_turn_id is view._mcp_live_turn is None
    assert not notes(view)
    await send(chunk(receipt(), turn="turn-1"))
    assert not notes(view)

    await send(turn_signal("turnStarted", "turn-2"))
    # Stale receipt FIRST in successor, before valid receipt/dedupe is set.
    await send(chunk(receipt(), turn="turn-1"))
    assert not notes(view)
    await send(turn_signal("turnSettled", "turn-1"))
    assert agent._active_turn_id == view._managed_turn_id == "turn-2"
    # Already validated but queued messages must also fail at UI delivery.
    view.post_message(messages.McpClientStatus(receipt(), "turn-1", session, agent))
    view.post_message(messages.McpClientStatus(receipt(), "turn-2", "foreign", agent))
    old_agent = Agent(agent.project_root_path, AGENT_DATA, session)
    view.post_message(messages.McpClientStatus(receipt(), "turn-2", session, old_agent))
    await pilot.pause()
    assert not notes(view)
    for update in [turn_signal("turnStarted", "foreign"),
                   turn_signal("turnSettled", "turn-2")]:
        await send(update, "foreign-session")
        assert agent._active_turn_id == view._managed_turn_id == "turn-2"
    await send(chunk(receipt(servers=[]), turn="turn-2"))
    assert len(notes(view)) == 1 and "no approved servers" in notes(view)[0]
    await send(turn_signal("turnSettled", "turn-2"))
    assert not notes(view) and view._mcp_live_turn is None


async def main() -> None:
    with TemporaryDirectory(prefix="toad-mcp-live-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"),
                          XDG_DATA_HOME=str(root / "data"),
                          XDG_STATE_HOME=str(root / "state"),
                          AGENT_COMMS_ROOT=str(root / "wire"))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(110, 34)) as pilot:
            await pilot.pause()
            assert isinstance(app.screen, MainScreen)
            view = app.screen.conversation
            agent = Agent(root, AGENT_DATA, "project")
            agent._message_target = view
            view.agent = agent
            await exercise_boundaries(agent, view, pilot)
            agent.rpc_session_update("project", turn_signal("turnStarted", "disconnect"))
            await pilot.pause()
            agent.rpc_session_update("project", chunk(receipt(), turn="disconnect"))
            await pilot.pause()
            assert notes(view)
            await agent.stop()
            await pilot.pause()
            assert not notes(view) and view._mcp_live_turn is None
            agent.rpc_session_update("project", chunk(receipt(), turn="disconnect"))
            await pilot.pause()
            assert not notes(view)
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("MCP live receipt/lifecycle: fixed session, stale-first, queued identity, settlement/disconnect PASS")


if __name__ == "__main__":
    asyncio.run(main())
