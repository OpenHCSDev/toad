"""Mounted exact-ID queue sink over actual Agent new/load/callback paths."""

from __future__ import annotations

import asyncio
import json
import os
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from runtime_fixture import ToadApp

from toad.acp import messages
from toad.acp.agent import Agent
from toad.queue_view import QueueProjection
from toad.widgets.prompt import QueueSummary
from toad.widgets.user_input import UserInput

F = json.loads(
    (Path(__file__).parent / "fixtures/acp_exact_id_queue_v1.json").read_text()
)
AGENT = {
    "name": "Queue fixture",
    "identity": "queue-fixture",
    "short_name": "fixture",
    "run_command": {"*": "true"},
    "protocol": "acp",
}


def update(state):
    return {
        "sessionUpdate": "agent_message_chunk",
        "content": {"type": "text", "text": ""},
        "_meta": {"agentComms": state},
    }


async def main():
    with TemporaryDirectory(prefix="toad-exact-queue-") as directory:
        root = Path(directory)
        os.environ.update(
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_DATA_HOME=str(root / "data"),
            XDG_STATE_HOME=str(root / "state"),
            AGENT_COMMS_ROOT=str(root / "wire"),
        )
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            view = app.screen.conversation
            agent = Agent(root, AGENT, "beta")
            agent._message_target = view
            view.agent = agent
            await pilot.pause()
            summary = view.query_one(QueueSummary)
            view.prompt.text = "local editable draft"
            view.input_delivery = {
                **view.input_delivery,
                "inputs": [{"inputId": "unknown-id", "status": "unknown"}],
            }
            durable = deepcopy(view.input_delivery)
            agent.get_input_delivery = AsyncMock(return_value=deepcopy(durable))

            async def load(metadata, before=(), new=False):
                class Response:
                    async def wait(self):
                        for state in before:
                            agent.rpc_session_update("beta", update(state))
                        return {
                            "sessionId": "beta",
                            "_meta": {"agentComms": {"promptQueue": True, **metadata}},
                        }

                with patch(
                    (
                        "toad.acp.agent.api.session_new"
                        if new
                        else "toad.acp.agent.api.session_load"
                    ),
                    return_value=Response(),
                ):
                    await (agent.acp_new_session() if new else agent.acp_load_session())
                await pilot.pause()

            async def callback(state, session="beta"):
                agent.rpc_session_update(session, update(state))
                await pilot.pause()
                assert view.prompt.text == "local editable draft"
                assert view.input_delivery == durable

            def echoes():
                return len(view.query(UserInput))

            def painted(text, artifact):
                assert text in summary.render().plain, summary.render().plain
                assert summary in app.screen._compositor.visible_widgets
                assert summary.region.height > 0
                frame = "\n".join(
                    strip.text for strip in app.screen._compositor.render_strips()
                )
                assert text in frame, frame
                svg = app.export_screenshot()
                assert "a" * 32 not in svg and "b" * 32 not in svg
                if output := os.environ.get("QUEUE_EVIDENCE_DIR"):
                    Path(output).mkdir(parents=True, exist_ok=True)
                    (Path(output) / f"{artifact}.svg").write_text(svg)

            await load(F["trustedLoad"], new=True)
            painted("Queued (2): same text", "queue-two-distinct-ids")
            initial_echoes = echoes()
            await callback({"inputStarted": F["updates"][0]["value"]})
            assert [row.input_id for row in view.queue_projection.items] == ["b" * 32]
            painted("Queued (1): same text", "exact-start-removes-only-one")
            assert echoes() == initial_echoes + 1
            for event in F["updates"]:
                await callback({event["kind"]: event["value"]})
            assert echoes() == initial_echoes + 1
            assert view.queued_prompts == []
            assert [row.input_id for row in view.queue_projection.restored] == [
                "b" * 32
            ]
            painted("Restored (1, read-only): same text", "restored-not-draft")
            # Duplicate restored snapshots and legacy callbacks never append a
            # draft, echo, or identify equal-text admitted inputs.
            await callback({"queueState": F["updates"][3]["value"]})
            view.post_message(messages.PromptQueueUpdate([], ["same text"]))
            view.post_message(messages.InputStarted("same text"))
            await pilot.pause()
            assert (
                view.prompt.text == "local editable draft"
                and echoes() == initial_echoes + 1
            )
            await callback({"queueState": None, "queue": [], "restored": ["same text"]})
            assert view.queue_projection.status == "unavailable"
            painted("Remote queue unavailable", "null-not-consumed")
            assert view.input_delivery == durable
            await load(F["nextTrustedLoad"])
            assert view.queue_projection.status == "available"
            assert (
                not view.queue_projection.items and not view.queue_projection.restored
            )
            await callback({"queueState": F["lateOldUpdate"]["value"]})
            assert view.queue_projection == QueueProjection("available")
            # Retired-agent and delayed mounted receipts cannot repaint.
            retired = agent
            stale = messages.QueueViewUpdate(
                QueueProjection("available"), (), retired, "beta", 99999
            )
            agent = Agent(root, AGENT, "beta")
            agent.get_input_delivery = AsyncMock(return_value=deepcopy(durable))
            agent._message_target = view
            view.agent = agent
            race = F["prebindRace"]
            await load(
                race["delayedTrustedLoad"],
                before=[{"queueState": race["callbackBeforeTrustedResult"]}],
            )
            painted("Remote queue unavailable", "prebind-floor")
            agent.rpc_session_update(
                "beta", {"sessionUpdate": "config_option_update", "configOptions": []}
            )
            await pilot.pause()
            assert agent._queue_view.scope is None
            assert view.queue_projection.status == "unavailable"
            await load(race["subsequentTrustedLoad"])
            retired.rpc_session_update(
                "beta", update({"queueState": F["trustedLoad"]["queueState"]})
            )
            view.post_message(stale)
            await pilot.pause()
            assert view.queue_projection == QueueProjection("available")
            stale_same_agent = messages.QueueViewUpdate(
                view.queue_projection, (), agent, "beta", agent._queue_sequence
            )
            await callback({"queueState": None})
            view.agent = None
            view.agent = agent
            view.post_message(stale_same_agent)
            await pilot.pause()
            painted("Remote queue unavailable", "same-agent-remount-null")
            assert (
                view.prompt.text == "local editable draft"
                and view.input_delivery == durable
            )
            await agent.stop()
            await pilot.pause()
            painted("Remote queue unavailable", "stopped")
            print(
                "PASS: mounted exact IDs/start/restore, null/draft/UNKNOWN, prebind/reconnect/rebase, retired/remount fencing"
            )


if __name__ == "__main__":
    asyncio.run(main())
