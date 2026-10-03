"""Owner polling must not reconstruct registries on the UI thread."""

import asyncio
import os
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

from agent_comms.child_process import ProcessIdentity
from agent_comms.comms import wire
from agent_comms.runtime import RuntimeProxy
from agent_comms.threads import Thread
from comms_boundary_fixture import attach_registered_coordination
from runtime_fixture import ToadApp

from toad.acp.agent import Agent


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-owner-reader-") as directory:
        root = Path(directory)
        os.environ.update(
            XDG_STATE_HOME=str(root / "state"),
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_DATA_HOME=str(root / "data"),
            AGENT_COMMS_ROOT=str(root / "first"),
        )
        roots = [root / "first", root / "second"]
        for source in roots:
            wire(source).registry.declare(
                Thread(
                    "owner",
                    frozenset(),
                    str(root),
                    process_identity=ProcessIdentity.capture(os.getpid()),
                )
            )
        agent = Agent(root, {"name": "fixture", "run_command": {"*": "false"}}, None)
        attach_registered_coordination(agent, str(roots[0]), "owner")
        ui_thread = threading.get_ident()
        constructors = []
        requests = []

        def construct(source):
            constructors.append((str(source), threading.get_ident()))
            assert threading.get_ident() != ui_thread, (
                "Registry reconstruction blocked the UI thread"
            )
            return wire(source)

        async def request(proxy, method, **params):
            requests.append((proxy._comms, proxy.session_id, method, params))
            return {"ok": True}

        with (
            patch("toad.acp.transcript_reader.wire", construct),
            patch.object(RuntimeProxy, "request", request),
        ):
            await asyncio.gather(*(agent.controller.request_owner("fixture") for _ in range(6)))
            assert len(constructors) == 1 and len(requests) == 6
            assert all((row[0] is requests[0][0] for row in requests))
            attach_registered_coordination(agent, str(roots[1]), agent.coordination.thread.name)
            await agent.controller.request_owner("fixture", revision=2)
            assert len(constructors) == 2
            assert requests[-1][0].root == roots[1] and requests[-1][3] == {
                "revision": 2
            }
        entered, release = (threading.Event(), threading.Event())

        def blocked(source):
            entered.set()
            if not release.wait(5):
                raise TimeoutError("Fixture did not release owner initialization")
            return wire(source)

        attach_registered_coordination(agent, str(roots[0]), agent.coordination.thread.name)
        try:
            with (
                patch("toad.acp.transcript_reader.wire", blocked),
                patch.object(RuntimeProxy, "request", request),
            ):
                pending = asyncio.create_task(agent.controller.request_owner("must-not-send"))
                assert await asyncio.to_thread(entered.wait, 2)
                attach_registered_coordination(
                    agent, str(roots[1]), agent.coordination.thread.name
                )
                release.set()
                try:
                    await pending
                except ValueError as error:
                    assert "identity changed" in str(error)
                else:
                    raise AssertionError("An obsolete owner binding sent a request")
        finally:
            release.set()
        assert all((row[2] != "must-not-send" for row in requests))
        app = ToadApp(project_dir=str(root))
        async with app.run_test() as pilot:
            await pilot.pause()
            shared = app.coordination_access.service
            app.selected_session.conversation.bind_agent(agent)
            with patch(
                "toad.acp.transcript_reader.wire",
                side_effect=AssertionError("Shared reader reconstructed"),
            ):
                async with agent.controller.transcripts.bind(str(shared.root)) as reader:
                    assert reader is shared
            assert reader is shared
        await asyncio.get_running_loop().shutdown_default_executor()
    print(
        "owner reader: off-loop single initialization, shared concurrent polls, root invalidation and no stale RPC dispatch passed"
    )


if __name__ == "__main__":
    asyncio.run(main())
