"""Agents reuse the running application's Core owner and cannot rebind its root."""

import asyncio
from pathlib import Path

import pytest
from agent_comms.errors import RouteChangedError
from agent_comms.tools import CommsServedRootTool

from support.roots import installed_wire
from support.workspace import Workspace


async def test_agents_share_the_running_interfaces_core_owner(workspace: Workspace):
    async with workspace.app() as ui:
        agents = (ui.detached_agent("first"), ui.detached_agent("second"))
        owner = ui.app.coordination_access.observation.observed()
        original = owner.core
        readers = await asyncio.gather(*(
            agent.controller.transcripts.core(str(owner.root)) for agent in agents))
        assert all(reader == original for reader in readers)
        served = await asyncio.gather(*(
            asyncio.to_thread(reader.call, CommsServedRootTool()) for reader in readers))
        assert all(Path(answer.root) == owner.root for answer in served)
        assert ui.app.coordination_access.observation is owner
        assert all(agent.controller.transcripts is ui.app.coordination_access.transcripts
                   for agent in agents)


async def test_another_root_does_not_replace_the_running_interfaces_core_owner(workspace: Workspace):
    other = installed_wire(workspace.roots.attempt / "second")
    async with workspace.app() as ui:
        agent = ui.detached_agent("reader")
        owner = ui.app.coordination_access.observation.observed()
        original = owner.core
        with pytest.raises(RouteChangedError):
            await agent.controller.transcripts.core(str(other.root))
        reader = await agent.controller.transcripts.core(str(owner.root))
        assert reader == original
        assert Path((await asyncio.to_thread(reader.call, CommsServedRootTool())).root) == owner.root
        assert ui.app.coordination_access.observation is owner
