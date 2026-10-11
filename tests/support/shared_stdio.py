"""A real stdio ACP agent process (Core's own client) that several Toad sessions attach to."""

from __future__ import annotations

from contextlib import asynccontextmanager
import os
import shlex
import sys

STDIO_AGENT = '''
import asyncio
from agent_comms.acp import CommsClient
from agent_comms.comms import wire
from acp import run_agent
async def main():
    client = CommsClient(wire(), auto_wake=False, use_unstable_protocol=True)
    try:
        await run_agent(client, use_unstable_protocol=client.use_unstable_protocol)
    finally:
        await client.shutdown()
asyncio.run(main())
'''


def stdio_agent_definition():
    """The agent definition whose process runs Core's ACP client over stdio."""
    from toad.agent_schema import AgentDefinition

    return AgentDefinition("real-attachments", "Real attachments", {"*": shlex.join([sys.executable, "-c", STDIO_AGENT])})


@asynccontextmanager
async def threads_owned_here(comms, project, names=("alpha", "beta")):
    """Declare `names` as threads of `project`, owned by this process through Core's ACP agent."""
    from agent_comms.acp import CommsAgent

    owner = CommsAgent(comms, runtime_enabled=True, auto_wake=False)
    try:
        for name in names:
            comms.threads.claim_thread(name, tags=frozenset({"acp"}), worktree=str(project))
            comms.threads.restore_stopped(comms.registry.snapshot(), (name,))
            thread = comms.owners.acquire_thread(name, owner_pid=os.getpid())
            await owner.sessions.bind_owned(thread, name)
        yield owner
    finally:
        await owner.shutdown()
