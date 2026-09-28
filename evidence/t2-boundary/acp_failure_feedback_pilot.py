"""Mounted UI consumes provider failure notifications captured from actual native stdio."""

import asyncio
import json
import os
import tempfile
from pathlib import Path

from agent_comms.acp_extension import (
    RequestFailedUpdate,
    TurnSettledUpdate,
    TurnStartedUpdate,
    decode_updates,
    encode_updates,
)
from agent_comms.acp_failure import ACPFailure
from runtime_fixture import ToadApp

from toad.acp.agent import Agent


async def main():
    receipt = json.loads(Path(os.environ["T2_ERROR_RECEIPT"]).read_text())
    with tempfile.TemporaryDirectory(
        prefix="t2-feedback-", dir="/var/tmp"
    ) as directory:
        root = Path(directory)
        os.environ.update(
            AGENT_COMMS_ROOT=str(root / "wire"),
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_STATE_HOME=str(root / "state"),
            XDG_DATA_HOME=str(root / "data"),
        )
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            view = app.screen.conversation
            agent = Agent(
                root,
                {
                    "name": "T2",
                    "identity": "t2",
                    "short_name": "t2",
                    "run_command": {"*": "true"},
                    "protocol": "acp",
                },
                receipt["session_id"],
            )
            agent._message_target = view
            view.agent = agent
            view.prompt.text = "unchanged next draft"
            reports = []
            for packet in receipt["notifications"]:
                update = packet.get("params", {}).get("update", {})
                facts = tuple(
                    fact
                    for fact in decode_updates(update.get("_meta"))
                    if isinstance(
                        fact,
                        (RequestFailedUpdate, TurnStartedUpdate, TurnSettledUpdate),
                    )
                )
                if not facts:
                    continue
                reports.extend(
                    fact for fact in facts if isinstance(fact, RequestFailedUpdate)
                )
                await agent.server.call(
                    {
                        "jsonrpc": "2.0",
                        "method": "session/update",
                        "params": {
                            "sessionId": agent.session_id,
                            "update": {
                                "sessionUpdate": "agent_message_chunk",
                                "content": {"type": "text", "text": ""},
                                "_meta": encode_updates(*facts),
                            },
                        },
                    }
                )
                await pilot.pause()
            assert len(reports) == 1
            screen = "\n".join(
                strip.text for strip in app.screen._compositor.render_strips()
            )
            assert "Provider usage limit reached" in screen, screen
            assert "usage limit" in screen and "has been reached" in screen, screen
            assert "input not retried" in screen, screen
            assert view.prompt.text == "unchanged next draft"
            assert view.busy_count == 0
            # Exact nested shape from the owner's recorded -32603 failure.
            nested = ACPFailure.from_error(
                -32603,
                "Internal error",
                {
                    "error": {
                        "code": -32603,
                        "message": "Internal error",
                        "data": {
                            "details": "Selected summary failed: Codex error: The usage limit has been reached (outcome uncertain; input not retried)"
                        },
                    }
                },
            )
            assert nested.title == reports[0].failure.title
            assert nested.input_disposition == "Unconfirmed — input not retried"
            assert app._exception is None
    print(
        "Installed mounted actual native quota feedback: provider reason/action/disposition visible; composer retained; no retry"
    )


if __name__ == "__main__":
    asyncio.run(main())
