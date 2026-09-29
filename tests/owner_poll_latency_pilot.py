"""Fixed owner-poll workload: registry preparation cost without provider/network time."""

import asyncio
import importlib
import json
import os
import statistics
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

from agent_comms.child_process import ProcessIdentity
from agent_comms.comms import wire
from agent_comms.runtime import RuntimeProxy
from agent_comms.threads import Thread
from comms_boundary_fixture import attach_registered_coordination

from toad.acp.agent import Agent


async def main():
    importlib.import_module("toad.app")
    with tempfile.TemporaryDirectory(prefix="toad-owner-poll-") as directory:
        root = Path(directory)
        os.environ["XDG_STATE_HOME"] = str(root / "state")
        comms = wire(root / "wire")
        for index in range(100):
            comms.threads.register(
                Thread(
                    f"worker-{index}",
                    frozenset({"shared", "test"}),
                    str(root),
                    process_identity=ProcessIdentity.capture(os.getpid()),
                )
            )
        agent = Agent(root, {"name": "fixture", "run_command": {"*": "false"}}, None)
        attach_registered_coordination(agent, str(comms.root), "worker-0")
        ui_thread = threading.get_ident()
        builds = []

        def construct(source):
            builds.append(threading.get_ident())
            return wire(source)

        async def reply(proxy, method, **params):
            return {"thread": proxy.session_id}

        durations, cpu = ([], [])
        with (
            patch("agent_comms.comms.wire", construct),
            patch.object(RuntimeProxy, "request", reply),
        ):
            for _ in range(20):
                begin, before_cpu = (time.perf_counter(), time.thread_time())
                assert await agent.controller.request_owner("goal_snapshot") == {
                    "thread": "worker-0"
                }
                durations.append((time.perf_counter() - begin) * 1000)
                cpu.append((time.thread_time() - before_cpu) * 1000)
        print(
            json.dumps(
                {
                    "boundary": "owner request preparation; fixture transport returns immediately",
                    "polls": 20,
                    "registry_threads": 100,
                    "constructors": len(builds),
                    "ui_constructors": builds.count(ui_thread),
                    "median_ms": round(statistics.median(durations), 3),
                    "max_ms": round(max(durations), 3),
                    "total_ui_cpu_ms": round(sum(cpu), 3),
                }
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
