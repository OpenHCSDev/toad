"""Real Core thread mutations keep their declared data and original source."""
import os

import pytest
from agent_comms.child_process import ProcessIdentity

from support.agents import RecordedEvents, deliver
from support.coordination import carrying, registered_coordination_fact
from toad.core.events import CoreEvent


async def bind(ui, workspace, name):
    workspace.thread(name, running=True)
    agent = ui.detached_agent(name)
    ui.attach_agent(agent)
    await deliver(agent, carrying(registered_coordination_fact(
        workspace.comms, name, worktree=workspace.project,
        owner=ProcessIdentity.capture(os.getpid()),
    )))
    return agent


async def test_project_change_publishes_the_real_checkout(workspace):
    target = workspace.project / "changed-project"
    target.mkdir()
    async with workspace.app() as ui:
        agent = await bind(ui, workspace, "source")
        events = RecordedEvents()
        with agent.events.subscribe(CoreEvent, events.receive):
            result = await agent.update_project(str(target))
        assert result == str(target)
        assert agent.project_root_path == target
        assert workspace.comms.registry.require("source").project_path == target
        event, = events
        assert event.update.worktree.path == target
        assert agent.observed_thread() == (str(workspace.comms.root), "source")


async def test_rename_keeps_canonical_name_distinct_from_display_title(workspace):
    async with workspace.app() as ui:
        agent = await bind(ui, workspace, "source")
        await agent.set_session_name("A chosen display title")
        root, name = agent.observed_thread()
        assert root == str(workspace.comms.root)
        current = workspace.comms.registry.require(name)
        assert current.title.require("renaming must publish a title") == "A chosen display title"
        assert agent.coordination_attachment.title == "A chosen display title"
        assert current.incarnation == agent.coordination_attachment.tool_scope.recipient


async def test_captured_attachment_cannot_mutate_a_replacement_thread(workspace):
    target = workspace.project / "refused-project"
    target.mkdir()
    async with workspace.app() as ui:
        agent = await bind(ui, workspace, "original")
        original = agent.coordination_attachment
        workspace.thread("replacement", running=True)
        await deliver(agent, carrying(registered_coordination_fact(
            workspace.comms, "replacement", worktree=workspace.project,
            owner=ProcessIdentity.capture(os.getpid()),
        )))
        with pytest.raises(ValueError, match="owner identity changed"):
            await original.update_project(agent, str(target))
        assert workspace.comms.registry.require("original").project_path == workspace.project
        assert workspace.comms.registry.require("replacement").project_path == workspace.project
        assert agent.project_root_path == workspace.project
        assert agent.observed_thread() == (str(workspace.comms.root), "replacement")
