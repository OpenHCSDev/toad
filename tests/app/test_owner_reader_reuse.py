"""Agents reach the running application's one Core and cannot rebind it to another root."""

import asyncio

import pytest
from agent_comms.core_access import LocalCoreAccess
from agent_comms.errors import RouteChangedError

from support.roots import installed_wire


async def test_agents_share_the_running_interfaces_core(workspace):
    async with workspace.app() as ui:
        agents = (ui.detached_agent("first"), ui.detached_agent("second"))
        shared = ui.core_service
        cores = await asyncio.gather(*(
            agent.controller.transcripts.core(str(shared.root)) for agent in agents))
        assert all(core == LocalCoreAccess(shared) for core in cores)
        assert all(agent.controller.transcripts is ui.app.coordination_access.transcripts
                   for agent in agents)


async def test_another_root_does_not_replace_the_running_interfaces_core(workspace):
    other = installed_wire(workspace.roots.attempt / "second")
    async with workspace.app() as ui:
        agent = ui.detached_agent("reader")
        shared = ui.core_service
        with pytest.raises(RouteChangedError):
            await agent.controller.transcripts.core(str(other.root))
        assert await agent.controller.transcripts.core(str(shared.root)) == LocalCoreAccess(shared)
        assert ui.core_service is shared
