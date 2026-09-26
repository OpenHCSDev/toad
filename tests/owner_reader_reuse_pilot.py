"""Owner polling must not reconstruct registries on the UI thread."""

import asyncio
import os
from pathlib import Path
import tempfile
import threading
from unittest.mock import patch

from agent_comms import Thread, wire
from agent_comms.runtime import RuntimeProxy
from toad.acp.agent import Agent


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-owner-reader-") as directory:
        root = Path(directory)
        os.environ.update(XDG_STATE_HOME=str(root / "state"))
        roots = [root / "first", root / "second"]
        for source in roots:
            wire(source).register(Thread("owner", frozenset(), str(root), pid=os.getpid()))
        agent = Agent(root, {"name": "fixture", "run_command": {"*": "false"}}, None)
        agent._coordination_root, agent._coordination_thread = str(roots[0]), "owner"
        ui_thread = threading.get_ident()
        constructors = []
        requests = []

        def construct(source):
            constructors.append((str(source), threading.get_ident()))
            assert threading.get_ident() != ui_thread, "Registry reconstruction blocked the UI thread"
            return wire(source)

        async def request(proxy, method, **params):
            requests.append((proxy._comms, proxy.session_id, method, params))
            return {"ok": True}

        with patch("agent_comms.wire", construct), patch("agent_comms.operations.wire", construct), \
                patch.object(RuntimeProxy, "request", request):
            await asyncio.gather(*(agent._owner_request("fixture") for _ in range(6)))
            assert len(constructors) == 1 and len(requests) == 6
            assert all(row[0] is requests[0][0] for row in requests)
            # Reader reuse is not caching RPC responses or routing identity.
            agent._coordination_root = str(roots[1])
            await agent._owner_request("fixture", revision=2)
            assert len(constructors) == 2
            assert requests[-1][0].root == roots[1] and requests[-1][3] == {"revision": 2}

        entered, release = threading.Event(), threading.Event()

        def blocked(source):
            entered.set()
            if not release.wait(5):
                raise TimeoutError("Fixture did not release owner initialization")
            return wire(source)

        agent._coordination_root = str(roots[0])
        try:
            with patch("agent_comms.wire", blocked), patch.object(RuntimeProxy, "request", request):
                pending = asyncio.create_task(agent._owner_request("must-not-send"))
                assert await asyncio.to_thread(entered.wait, 2)
                agent._coordination_root = str(roots[1])
                release.set()
                try:
                    await pending
                except ValueError as error:
                    assert "identity changed" in str(error)
                else:
                    raise AssertionError("An obsolete owner binding sent a request")
        finally:
            release.set()
        assert all(row[2] != "must-not-send" for row in requests)
    print("owner reader: off-loop single initialization, shared concurrent polls, root invalidation and no stale RPC dispatch passed")


if __name__ == "__main__":
    asyncio.run(main())
