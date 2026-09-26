"""Provider-free package live MCP receipt gating and redacted projection pilot."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from runtime_fixture import ToadApp

from toad.acp.agent import Agent
from toad.screens.main import MainScreen
from toad.widgets.note import Note


INPUT = "a" * 32


def receipt(**overrides: object) -> dict:
    base = {
        "version": 1,
        "source": "pi-mcp-client",
        "inputId": INPUT,
        "state": "running",
        "lifetime": "turn",
        "servers": [
            {
                "id": "fixture",
                "scope": "project",
                "state": "ready",
                "calls": "confirm",
                "tools": 2,
                "resources": 1,
                "prompts": 0,
            }
        ],
    }
    base.update(overrides)
    return base


def chunk(
    value: object,
    input_id: object = INPUT,
    turn: object = None,
    text: object = "",
) -> dict:
    envelope: dict = {"mcpClient": value, "inputId": input_id}
    if turn is not None:
        envelope["turnId"] = turn
    return {
        "sessionUpdate": "agent_message_chunk",
        "content": {"type": "text", "text": text},
        "_meta": {"agentComms": envelope},
    }


def turn_signal(kind: str, turn: str) -> dict:
    return {
        "sessionUpdate": "user_message_chunk",
        "content": {"type": "text", "text": ""},
        "_meta": {"agentComms": {kind: True, "turnId": turn}},
    }


def notes(view: object) -> list[str]:
    return [
        str(widget.render())  # type: ignore[union-attr]
        for widget in view.contents.children  # type: ignore[attr-defined]
        if isinstance(widget, Note)
    ]


async def main() -> None:
    with TemporaryDirectory(prefix="toad-mcp-live-") as directory:
        root = Path(directory)
        os.environ.update(
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_DATA_HOME=str(root / "data"),
            XDG_STATE_HOME=str(root / "state"),
            AGENT_COMMS_ROOT=str(root / "wire"),
        )
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(110, 34)) as pilot:
            await pilot.pause()
            assert isinstance(app.screen, MainScreen)
            view = app.screen.conversation
            agent = Agent(
                root,
                {
                    "name": "Fixture",
                    "identity": "fixture",
                    "short_name": "fixture",
                    "run_command": {"*": "true"},
                    "protocol": "acp",
                },
                "fixture",
            )
            agent._message_target = view

            # No active turn: any receipt is invisible regardless of validity.
            agent.rpc_session_update("fixture", chunk(receipt()))
            await pilot.pause()
            assert not notes(view)

            from toad.acp import messages as acp_messages

            agent.rpc_session_update("fixture", turn_signal("turnStarted", "turn-1"))
            await view.on_turn_started(acp_messages.TurnStarted("turn-1"))
            # No turn-identity envelope: fail closed even inside an active turn.
            agent.rpc_session_update("fixture", chunk(receipt()))
            # Bound receipt is rendered once; duplicates and stale variants are not.
            agent.rpc_session_update("fixture", chunk(receipt(), turn="turn-1"))
            agent.rpc_session_update(
                "fixture", chunk(receipt(), turn="turn-1")
            )  # duplicate
            agent.rpc_session_update(
                "fixture", chunk(receipt(), input_id="forged", turn="turn-1")
            )
            agent.rpc_session_update("fixture", chunk({"version": 2}, turn="turn-1"))
            agent.rpc_session_update(
                "fixture", chunk(receipt(version=True), turn="turn-1")
            )
            agent.rpc_session_update(
                "fixture", chunk(receipt(servers=[{"id": "x"}]), turn="turn-1")
            )
            agent.rpc_session_update(
                "fixture",
                chunk(
                    receipt(
                        servers=[
                            {
                                "id": "fixture",
                                "scope": "project",
                                "state": "denied",
                                "calls": "confirm",
                                "tools": 0,
                                "resources": 0,
                                "prompts": 0,
                            }
                        ]
                    ),
                    turn="turn-1",
                ),
            )
            agent.rpc_session_update(
                "fixture", chunk(receipt(inputId="b" * 32), turn="turn-1")
            )
            agent.rpc_session_update(
                "fixture", chunk(receipt(state="idle"), turn="turn-1")
            )
            agent.rpc_session_update(
                "fixture", chunk(receipt(), turn="turn-1", text="hello")
            )
            agent.rpc_session_update(
                "fixture", chunk(receipt(turn="x"), turn="turn-1")
            )  # wrong turn
            agent.rpc_session_update(
                "fixture",
                chunk(receipt()),
            )  # still no turn identity
            await pilot.pause()
            rendered = notes(view)
            assert len(rendered) == 1, rendered
            assert "fixture[project] ready calls=confirm tools=2" in rendered[0]
            assert "not a grant" in rendered[0]
            assert "forged" not in "".join(rendered)

            # A receipt after settlement is invisible even with a stale turn id.
            agent.rpc_session_update("fixture", turn_signal("turnSettled", "turn-1"))
            await view.on_turn_settled(acp_messages.TurnSettled("turn-1"))
            agent.rpc_session_update("fixture", chunk(receipt(), turn="turn-1"))
            await pilot.pause()
            assert notes(view) == rendered

            # A successor turn starts a fresh boundary; a replayed turn-1 receipt
            # cannot render there, while the bound turn-2 receipt does.
            agent.rpc_session_update("fixture", turn_signal("turnStarted", "turn-2"))
            await view.on_turn_started(acp_messages.TurnStarted("turn-2"))
            agent.rpc_session_update(
                "fixture", chunk(receipt(), turn="turn-1")
            )  # stale queued event
            agent.rpc_session_update(
                "fixture",
                chunk(
                    receipt(servers=[], inputId="c" * 32),
                    input_id="c" * 32,
                    turn="turn-2",
                ),
            )
            await pilot.pause()
            updated = notes(view)
            assert len(updated) == 2 and "no approved servers" in updated[1]
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print(
        "MCP live receipt: strict v1, active-turn gate, redacted turn-bound projection"
    )


if __name__ == "__main__":
    asyncio.run(main())
