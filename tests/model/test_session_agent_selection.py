"""SDK source selection preserves the operational owner and its captured authority."""
import os

import pytest
from agent_comms.acp_extension import CoordinationChangedUpdate, encode_updates
from agent_comms.child_process import ProcessIdentity
from agent_comms.ui_model.delivery import DeliveryView

from support.coordination import registered_coordination_fact
from support.workspace import Workspace
from toad.acp.client_session import ClientSessionRequest


def update_for(workspace: Workspace, name: str) -> CoordinationChangedUpdate:
    thread = workspace.thread(name)
    return registered_coordination_fact(
        workspace.comms, thread.name, owner=ProcessIdentity.capture(os.getpid()),
        worktree=workspace.project)


async def test_sdk_selection_preserves_resources_and_rejects_a_replaced_source(workspace: Workspace):
    agent = workspace.agents.detached_agent("source-selection")
    assert await agent.input_delivery() == DeliveryView()
    authority = ClientSessionRequest(agent, agent.session_id)
    resources = (agent.controller, agent.session, agent.process, agent.events,
                 agent.controller.session, agent.controller.terminals, agent.queue_attachment,
                 agent.session.disposition)
    consumer = agent.comms_consumer_class(agent, agent.session_id)
    await consumer.consume_metadata(encode_updates(update_for(workspace, "first-source")))
    first = agent.coordination
    selected_type = type(agent)
    request = agent.capture_owner_request(authority)
    assert request.coordination is first
    request.require()
    assert authority.current
    await consumer.consume_metadata(encode_updates(update_for(workspace, "second-source")))
    assert type(agent) is selected_type
    assert authority.current
    current = (agent.controller, agent.session, agent.process, agent.events,
               agent.controller.session, agent.controller.terminals, agent.queue_attachment,
               agent.session.disposition)
    assert all(before is after for before, after in zip(resources, current, strict=True))
    assert not request.current
    assert not agent.owner_read(request).accepts_turn()
    with pytest.raises(ValueError, match="owner identity changed"):
        request.require()
    agent.capture_owner_request(authority).require()


async def test_project_change_keeps_the_sdk_worktree_type(workspace: Workspace):
    agent = workspace.agents.detached_agent("project-selection")
    await agent.comms_consumer_class(agent, agent.session_id).consume_metadata(
        encode_updates(update_for(workspace, "project-owner")))
    target = workspace.project / "selected-project"
    target.mkdir()
    assert await agent.update_project(str(target)) == str(target)
    assert agent.coordination.worktree.path == target
    assert agent.project_root_path == target
