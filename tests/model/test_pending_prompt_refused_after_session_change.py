"""A real late reply cannot confirm a captured session that changed and returned."""

import asyncio

import pytest
from agent_comms.acp_extension import QueuePromptRequest

from support.agents import peer, script
from toad.acp.queue_attachment import QueueActionRefused
from toad.acp.client_session import UnconfirmedPromptResult
from toad.session_scope import AgentAttached


async def test_pending_prompt_reply_is_unconfirmed_when_the_session_changes_and_returns(workspace):
    async with workspace.app(binding=AgentAttached(peer("scripted"))) as ui:
        await ui.until_agent_ready()
        agent = ui.conversation.agent_binding
        session_id, original = agent.session_id, agent.controller.session
        body = script({"wait": "retired-prompt"})
        pending = asyncio.create_task(agent.send_prompt(body, request=QueuePromptRequest(body, True)))
        await ui.until(lambda: workspace.prompts_received() == [body],
                       why="the original request held by the actual peer")
        assert agent.controller.prompt_in_flight == 1
        # Exercise the binding owner's setter, not a patched prompt or ambient root.
        agent.session_id = "replacement-session"
        agent.session_id = session_id
        assert agent.controller.session is not original
        workspace.release("retired-prompt")
        outcome = await asyncio.wait_for(pending, 10)
        assert isinstance(outcome, UnconfirmedPromptResult)
        assert outcome.request.binding is original
        with pytest.raises(QueueActionRefused):
            outcome.require_confirmation()
        assert workspace.prompts_received() == [body]
        assert agent.controller.prompt_in_flight == 0
        assert not agent.controller._deferred_submissions
