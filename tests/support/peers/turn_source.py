"""One registry-backed ACP publisher for authored turn observations."""

from contextlib import AsyncExitStack, asynccontextmanager
from functools import partial
import os
from pathlib import Path
from unittest.mock import patch

from agent_comms.acp import CommsAgent
from agent_comms.comms import wire
from agent_comms.coordinator import Coordination
from agent_comms.launch_root import LaunchRoot
from agent_comms.launch_runtime import ThreadLaunch


@asynccontextmanager
async def turn_source(wire_root: Path, project: Path, session_id: str):
    """Retain declaration and attachment custody without sending native input."""
    with patch.dict(os.environ), LaunchRoot.from_path(wire_root).selected():
        ThreadLaunch.strip(os.environ)
        async with AsyncExitStack() as resources:
            project.mkdir(parents=True, exist_ok=True)
            comms = await Coordination.run_worker(partial(wire, wire_root))
            producer = CommsAgent(comms, runtime_enabled=False, auto_wake=False)
            resources.push_async_callback(producer.shutdown)

            def declare():
                thread = producer.sessions.declare_thread(str(project))
                resources.push_async_callback(Coordination.run_worker,
                                              partial(comms.owners.stop, thread.name))
                return thread

            thread = await Coordination.run_worker(declare)
            await producer.sessions.bind_owned(thread, session_id)
            yield producer
