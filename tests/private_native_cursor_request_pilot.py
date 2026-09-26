"""Independent-review regressions: fence actual new/load result side effects."""

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
from toad.widgets.native_history import NativeHistory

DATA = {
    "name": "Fixture",
    "identity": "fixture",
    "short_name": "fixture",
    "run_command": {"*": "true"},
    "protocol": "acp",
}
FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures/private_native_cursor_v1.json").read_text()
)


def response(session):
    cursor = deepcopy(FIXTURE["trustedLoad"]["cursor"])
    cursor["scope"]["sessionId"] = session
    return {
        "sessionId": session,
        "_meta": {"agentComms": {"privateNativeCursor": cursor}},
    }


class Response:
    def __init__(self):
        self.started = asyncio.Event()
        self.result = asyncio.get_running_loop().create_future()

    async def wait(self):
        self.started.set()
        return await self.result


async def main():
    with TemporaryDirectory(prefix="cursor-request-fence-") as directory:
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
                    initial_session = "old-session" if first_kind == "load" else None
                    agent = Agent(root, DATA, initial_session)
                    agent._message_target = view
                    view.agent = agent
                    await pilot.pause()
                    first, second = Response(), Response()
                    new_responses = [first, second] if first_kind == "new" else [second]
                    with (
                        patch(
                            "toad.acp.agent.api.session_new", side_effect=new_responses
                        ),
                        patch(
                            "toad.acp.agent.api.session_load", return_value=first
                        ) as load,
                    ):
                        call = (
                            agent.acp_new_session
                            if first_kind == "new"
                            else agent.acp_load_session
                        )
                        pending = asyncio.create_task(call())
                        await first.started.wait()
                        if first_kind == "load":
                            assert load.call_args.args[2] == "old-session"
                        if successor == "new":
                            replacement = asyncio.create_task(agent.acp_new_session())
                            await second.started.wait()
                            second.result.set_result(response("new-session"))
                            await replacement
                            await pilot.pause()
                            assert agent.session_id == "new-session"
                            assert view.native_history_status == "proven"
                        else:
                            await agent.stop()
                            await pilot.pause()
                        sequence = agent._private_cursor_sequence
                        current_session = agent.session_id
                        status = view.native_history_status
                        first.result.set_result(response("old-session"))
                        await pending
                        await pilot.pause()
                    assert agent.session_id == current_session
                    assert agent._private_cursor_sequence == sequence
                    assert view.native_history_status == status
                    if successor == "new":
                        assert (
                            agent._private_cursor.current.scope.session_id
                            == "new-session"
                        )
                        row = view.query_one(NativeHistory)
                        assert (
                            row.display
                            and row in app.screen._compositor.visible_widgets
                        )
                    else:
                        assert agent._private_cursor.current is None
                        assert status != "proven"
                    await agent.stop()
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print(
        "PASS mounted request fences: new/new, load/new, new/stop, load/stop; late result cannot mutate session or publish mislabeled proof"
    )


if __name__ == "__main__":
    asyncio.run(main())
