"""Mounted queue request/source fencing, independent of cursor verdicts."""

from __future__ import annotations

import asyncio
import json
import os
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from runtime_fixture import ToadApp

from toad.acp.agent import Agent
from toad.widgets.prompt import QueueSummary

DATA = {
    "name": "Fixture",
    "identity": "fixture",
    "short_name": "fixture",
    "run_command": {"*": "true"},
    "protocol": "acp",
}
F = json.loads(
    (Path(__file__).parent / "fixtures/acp_exact_id_queue_v1.json").read_text()
)


def response(session, next_owner=False):
    state = deepcopy(F["nextTrustedLoad" if next_owner else "trustedLoad"])
    state["queueBinding"]["sessionId"] = state["queueState"]["scope"]["sessionId"] = (
        session
    )
    return {"sessionId": session, "_meta": {"agentComms": state}}


class Response:
    def __init__(self):
        self.started = asyncio.Event()
        self.result = asyncio.get_running_loop().create_future()

    async def wait(self):
        self.started.set()
        return await self.result


async def main():
    with TemporaryDirectory(prefix="queue-request-fence-") as directory:
        root = Path(directory)
        os.environ.update(
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_DATA_HOME=str(root / "data"),
            XDG_STATE_HOME=str(root / "state"),
            AGENT_COMMS_ROOT=str(root / "wire"),
        )
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(115, 38)) as pilot:
            await pilot.pause()
            view = app.screen.conversation
            for first_kind in ("new", "load"):
                for successor in ("new", "stop"):
                    agent = Agent(
                        root, DATA, "old-session" if first_kind == "load" else None
                    )
                    agent._message_target = view
                    view.agent = agent
                    await pilot.pause()
                    view.prompt.text = "untouched local draft"
                    first, second = Response(), Response()
                    with (
                        patch(
                            "toad.acp.agent.api.session_new",
                            side_effect=(
                                [first, second] if first_kind == "new" else [second]
                            ),
                        ),
                        patch("toad.acp.agent.api.session_load", return_value=first),
                    ):
                        pending = asyncio.create_task(
                            agent.acp_new_session()
                            if first_kind == "new"
                            else agent.acp_load_session()
                        )
                        await first.started.wait()
                        if successor == "new":
                            replacing = asyncio.create_task(agent.acp_new_session())
                            await second.started.wait()
                            second.result.set_result(response("new-session"))
                            await replacing
                            await pilot.pause()
                            assert agent.session_id == "new-session"
                            assert view.queue_projection.status == "available"
                        else:
                            await agent.stop()
                            await pilot.pause()
                        before = (
                            agent.session_id,
                            agent._queue_sequence,
                            view.queue_projection,
                        )
                        first.result.set_result(response("old-session"))
                        await pending
                        await pilot.pause()
                        assert (
                            agent.session_id,
                            agent._queue_sequence,
                            view.queue_projection,
                        ) == before
                        assert view.prompt.text == "untouched local draft"
                        if successor == "new":
                            row = view.query_one(QueueSummary)
                            assert row in app.screen._compositor.visible_widgets
                            assert "Queued (2)" in row.render().plain
                        else:
                            assert view.queue_projection.status != "available"
                    await agent.stop()
            # A failed, retired local request cannot roll back a successor's
            # composer, even with identical text or the same receiving Agent.
            for successor in ("agent", "owner", "unavailable"):
                agent = Agent(root, DATA, "beta")
                agent._message_target = view
                view.agent = agent
                loaded = Response()
                loaded.result.set_result(response("beta"))
                with patch("toad.acp.agent.api.session_load", return_value=loaded):
                    await agent.acp_load_session()
                await pilot.pause()
                entered, release = asyncio.Event(), asyncio.Event()

                async def failed_send(
                    *args, entered=entered, release=release, **kwargs
                ):
                    entered.set()
                    await release.wait()
                    raise ValueError("delayed old request failure")

                with patch.object(agent, "send_prompt", side_effect=failed_send):
                    worker = view.send_prompt_to_agent("old request", queued=True)
                    await entered.wait()
                    if successor == "agent":
                        replacement = Agent(root, DATA, "beta")
                        replacement._message_target = view
                        view.agent = replacement
                    elif successor == "owner":
                        loaded = Response()
                        loaded.result.set_result(response("beta", next_owner=True))
                        with patch(
                            "toad.acp.agent.api.session_load", return_value=loaded
                        ):
                            await agent.acp_load_session()
                    else:
                        agent.rpc_session_update(
                            "beta",
                            {
                                "sessionUpdate": "session_info_update",
                                "_meta": {"agentComms": {"queueState": None}},
                            },
                        )
                    await pilot.pause()
                    view.prompt.text = "successor draft"
                    projection = view.queue_projection
                    release.set()
                    await worker.wait()
                    await pilot.pause()
                    assert view.prompt.text == "successor draft"
                    assert view.queue_projection == projection
            print(
                "PASS: queue new/new, load/new, new/stop, load/stop and retired Agent/owner/unavailable draft rollback fences"
            )


if __name__ == "__main__":
    asyncio.run(main())
