"""Mounted alias rollback and 32+1 prebind regressions; no provider or replay."""

from __future__ import annotations

import asyncio
import os
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from queue_view_pilot import AGENT, F, update
from runtime_fixture import ToadApp

from toad.acp.agent import Agent
from toad.acp.messages import QueueViewUpdate
from toad.queue_view import QueueProjection
from toad.widgets.prompt import QueueSummary


def attachment(metadata, session):
    """Adversarial aliases change only the attachment ID, never owner data."""
    value = deepcopy(metadata)
    value["queueBinding"]["sessionId"] = session
    value["queueState"]["scope"]["sessionId"] = session
    return value


async def main():
    with TemporaryDirectory(prefix="queue-bounds-alias-") as directory:
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
            view.prompt.text = "untouched local draft"
            durable = {
                **view.input_delivery,
                "inputs": [{"inputId": "unknown", "status": "unknown"}],
            }
            view.input_delivery = deepcopy(durable)

            async def fresh():
                agent = Agent(root, AGENT, "beta")
                agent.get_input_delivery = AsyncMock(return_value=deepcopy(durable))
                agent._message_target = view
                view.agent = agent
                await pilot.pause()
                return agent

            async def load(agent, metadata, before=()):
                class Response:
                    async def wait(self):
                        for state in before:
                            agent.rpc_session_update(agent.session_id, update(state))
                        return {"_meta": {"agentComms": metadata}}

                with patch("toad.acp.agent.api.session_load", return_value=Response()):
                    await agent.acp_load_session()
                await pilot.pause()
                assert view.prompt.text == "untouched local draft"
                assert view.input_delivery == durable

            def unavailable(name):
                assert view.queue_projection.status == "unavailable"
                summary = view.query_one(QueueSummary)
                assert summary in app.screen._compositor.visible_widgets
                frame = "\n".join(
                    strip.text for strip in app.screen._compositor.render_strips()
                )
                assert "Remote queue unavailable" in frame
                assert "Queued (2)" not in frame
                if output := os.environ.get("QUEUE_EVIDENCE_DIR"):
                    Path(output).mkdir(parents=True, exist_ok=True)
                    (Path(output) / f"{name}.svg").write_text(app.export_screenshot())

            for case in ("epoch", "revision"):
                agent = await fresh()
                await load(agent, F["trustedLoad"])
                newer = deepcopy(
                    F["nextTrustedLoad"] if case == "epoch" else F["trustedLoad"]
                )
                if case == "revision":
                    newer["queueState"] = deepcopy(F["updates"][1]["value"])
                agent.rpc_session_update(
                    "beta", update({"queueState": newer["queueState"]})
                )
                await pilot.pause()
                agent.session_id = "alias"
                await load(agent, attachment(F["trustedLoad"], "alias"))
                unavailable(f"alias-{case}-rollback-rejected")
                await load(agent, attachment(newer, "alias"))
                assert view.queue_projection.status == "available"
                assert [row.input_id for row in view.queue_projection.items] == (
                    [] if case == "epoch" else ["b" * 32]
                )
                # Old attachment callbacks are not made authoritative by the
                # alias-stable owner fences. Equal revision conflicts stay out.
                current = view.queue_projection
                agent.rpc_session_update(
                    "beta", update({"queueState": F["trustedLoad"]["queueState"]})
                )
                await pilot.pause()
                assert view.queue_projection == current
                conflict = attachment(newer, "alias")
                conflict["queueState"]["items"] = deepcopy(
                    F["trustedLoad"]["queueState"]["items"]
                )
                await load(agent, conflict)
                unavailable(f"alias-{case}-equal-conflict")
                await agent.stop()

            for case in (
                "same-key",
                "distinct-keys",
                "null",
                "surrogate-start",
                "rows33",
                "surrogate-snapshot",
            ):
                agent = await fresh()
                higher = F["prebindRace"]["callbackBeforeTrustedResult"]
                if case == "same-key":
                    before = [{"queueState": higher}] * 33
                elif case == "distinct-keys":
                    before = []
                    for index in range(32):
                        state = deepcopy(F["trustedLoad"]["queueState"])
                        state["scope"]["ownerThread"] = f"foreign-{index}"
                        before.append({"queueState": state})
                    before.append({"queueState": higher})
                elif case == "null":
                    before = [{"queueState": None}]
                elif case == "surrogate-start":
                    before = [
                        {"inputStarted": {**F["updates"][0]["value"], "text": "\ud800"}}
                    ]
                else:
                    state = deepcopy(F["trustedLoad"]["queueState"])
                    if case == "rows33":
                        state["items"] = [
                            {"inputId": str(i), "text": "body"} for i in range(33)
                        ]
                    else:
                        state["items"][0]["text"] = "\ud800"
                    before = [{"queueState": state}]
                await load(agent, F["trustedLoad"], before)
                unavailable(f"prebind-{case}")
                assert len(agent._queue_view._buffer) <= 32
                assert len(agent._queue_view._floors) <= 32
                agent.rpc_session_update("beta", update({"queueState": higher}))
                await pilot.pause()
                unavailable(f"prebind-{case}-callback-no-rebind")
                if case in ("same-key", "distinct-keys"):
                    await load(agent, F["trustedLoad"])
                    unavailable(f"prebind-{case}-old-load")
                await load(agent, F["nextTrustedLoad"])
                if case == "distinct-keys":
                    unavailable("distinct-evidence-loss-fresh-load")
                    sequence = agent._queue_sequence
                    view.agent = None
                    view.agent = agent
                    view.post_message(
                        QueueViewUpdate(
                            QueueProjection("available"),
                            (),
                            agent,
                            "beta",
                            sequence - 1,
                        )
                    )
                    await pilot.pause()
                    unavailable("distinct-evidence-loss-remount")
                    agent.session_id = "alias"
                    await load(agent, attachment(F["nextTrustedLoad"], "alias"))
                    unavailable("distinct-evidence-loss-alias")
                    await agent.stop()
                    agent = await fresh()
                    await load(agent, F["nextTrustedLoad"])
                assert view.queue_projection.status == "available"
                assert not view.queue_projection.items
                assert (
                    view.prompt.text == "untouched local draft"
                    and view.input_delivery == durable
                )
                await agent.stop()
        assert app._exception is None
    print(
        "PASS: mounted alias epoch/revision/equal-conflict fences; 32+1 overflow/cardinality, null/surrogate poison, remount/fresh recovery; draft/UNKNOWN unchanged"
    )


if __name__ == "__main__":
    asyncio.run(main())
