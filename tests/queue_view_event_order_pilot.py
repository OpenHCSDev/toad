"""Provider-free baseline probes for identity-free queue projection.

Uses only disposable state and actual ACP Agent/Conversation dispatch. No Pi,
provider calls, or historic input replay. These are deterministic protocol/UI
counterexamples, NOT a claim about the root cause of any live ghost input.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from runtime_fixture import ToadApp
from toad.acp.agent import Agent
from toad.widgets.user_input import UserInput

AGENT_DATA = {
    "name": "Queue fixture", "identity": "queue-fixture", "short_name": "queue-fixture",
    "run_command": {"*": "true"}, "protocol": "acp",
}


def update(state: dict) -> dict:
    return {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": ""},
            "_meta": {"agentComms": state}}


async def probe() -> dict:
    with TemporaryDirectory(prefix="toad-queue-order-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"),
                          XDG_CONFIG_HOME=str(root / "config"),
                          XDG_DATA_HOME=str(root / "data"),
                          XDG_STATE_HOME=str(root / "state"))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(110, 34)) as pilot:
            await pilot.pause()
            view = app.screen.conversation
            agent = Agent(root, AGENT_DATA, "project")
            agent._message_target = view
            view.agent = agent

            async def send(state, *, source=agent, session="project"):
                source.rpc_session_update(session, update(state))
                await pilot.pause()

            def echoes(text):
                return sum(widget.content == text for widget in view.query(UserInput))

            # Two different input IDs may legitimately have identical text.
            await send({"queue": ["same text", "same text"]})
            started = {"inputStarted": {"inputId": "b" * 32, "text": "same text"}}
            await send(started)
            await send(started)  # Duplicate receipt, not another input.
            duplicate = {"remainingRows": list(view.queued_prompts), "echoes": echoes("same text")}

            # Delayed pre-start queue snapshot must not resurrect consumed input.
            await send({"queue": ["ordered input"]})
            await send({"inputStarted": {"inputId": "c" * 32, "text": "ordered input"}})
            await send({"queue": ["ordered input"]})
            resurrected = list(view.queued_prompts)

            # Actual foreign-session raw callbacks must not touch this view.
            await send({"queue": ["owned row"]})
            await send({"queue": ["foreign row"]}, session="foreign-session")
            foreign_snapshot = list(view.queued_prompts)
            await send({"queue": ["owned row"]})
            await send({"inputStarted": {"inputId": "d" * 32, "text": "owned row"}},
                       session="foreign-session")
            foreign_start = {"rows": list(view.queued_prompts), "echoes": echoes("owned row")}

            # A retired Agent still holding the target cannot overwrite successor.
            successor = Agent(root, AGENT_DATA, "project")
            successor._message_target = view
            view.agent = successor
            await send({"queue": ["successor row"]}, source=successor)
            await send({"queue": ["retired row"]}, source=agent)
            retired_snapshot = list(view.queued_prompts)

            view.prompt.text = "draft"
            restored = {"queue": [], "restored": ["recover once"]}
            await send(restored, source=successor)
            await send(restored, source=successor)
            restored_text = view.prompt.text
            assert app._exception is None
            result = {
                "duplicateStarted": duplicate,
                "staleSnapshotRows": resurrected,
                "foreignSnapshotRows": foreign_snapshot,
                "foreignStarted": foreign_start,
                "retiredAgentRows": retired_snapshot,
                "duplicateRestoreComposer": restored_text,
                "defects": {
                    "duplicateStartedConsumedSecondIdenticalInput": duplicate["remainingRows"] != ["same text"],
                    "duplicateStartedEcho": duplicate["echoes"] != 1,
                    "staleSnapshotResurrectedInput": bool(resurrected),
                    "foreignSnapshotMutatedView": foreign_snapshot != ["owned row"],
                    "foreignStartedMutatedView": foreign_start != {"rows": ["owned row"], "echoes": 0},
                    "retiredAgentMutatedSuccessor": retired_snapshot != ["successor row"],
                    "duplicateRestore": restored_text != "draft\n\nrecover once",
                },
                "scope": "Deterministic disposable UI repro only; live ghost cause unconfirmed; no replay",
            }
            await agent.stop()
            await successor.stop()
        await asyncio.get_running_loop().shutdown_default_executor()
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--expect-baseline-defects", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(probe())
    print(json.dumps(result, indent=2))
    if args.expect_baseline_defects:
        assert all(result["defects"].values()), "Pinned baseline changed; investigate each probe"
    else:
        assert not any(result["defects"].values()), "Queue projection violates identity/order boundaries"
