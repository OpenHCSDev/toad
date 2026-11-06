"""Rebinding or reopening never revives a captured prompt or queue authority."""
from agent_comms.nominal.field_codec import AcpSessionId
import pytest
from acp.exceptions import RequestError

from toad.acp.client_session import ClientSessionRequest, QueueSessionRequest
from toad.acp.queue_attachment import QueueActionRefused
from toad.acp.status import UnreportedStopReason


async def test_rebinding_back_to_the_same_name_refuses_captured_requests(app_agents):
    agent = app_agents.detached_agent("A", identity="prompt-session")
    prompt = ClientSessionRequest(agent, agent.session_id)
    queue = QueueSessionRequest(agent, agent.session_id)
    disposition = agent.session.disposition
    try:
        assert prompt.current and queue.current
        agent.session_id = AcpSessionId("B")
        agent.session_id = AcpSessionId("A")
        assert agent.session.disposition is disposition
        assert agent.session.accepts_session("A")
        for request in (prompt, queue):
            assert request.retired
            with pytest.raises(RequestError):
                request.require()
        assert prompt.unconfirmed("captured session retired") is UnreportedStopReason
        with pytest.raises(QueueActionRefused):
            queue.unconfirmed("captured session retired")
    finally:
        await agent.stop()


async def test_reopening_the_same_binding_refuses_the_original_disposition(app_agents):
    agent = app_agents.detached_agent("A", identity="prompt-disposition")
    request = ClientSessionRequest(agent, agent.session_id)
    try:
        assert request.current
        agent.session.close()
        agent.session.reopen()
        assert agent.controller.session is request.binding
        assert agent.session.accepts_session("A")
        assert agent.session.disposition is not request.disposition
        with pytest.raises(RequestError):
            request.require()
    finally:
        await agent.stop()
