"""Actual prompt-building and session custody deny stale effects before transport."""
import asyncio
import threading
from pathlib import Path
import pytest
from agent_comms.acp_extension import QueuePromptRequest
from toad import jsonrpc
from toad.acp.agent import Agent
from toad.acp import agent_controller


def test_pending_prompt_build_rejects_session_return_without_dispatch(tmp_path, monkeypatch):
    async def run():
        agent = Agent(tmp_path, {'name': 'input-custody', 'run_command': {'*': 'true'}}, 'A')
        entered, release = threading.Event(), threading.Event()
        real_build = agent_controller.build_prompt
        def pending_build(project, text):
            entered.set()
            assert release.wait(5), 'Test failed to release resource preparation'
            return real_build(project, text)
        dispatched = []
        monkeypatch.setattr(agent_controller, 'build_prompt', pending_build)
        monkeypatch.setattr(agent.process, 'send', dispatched.append)
        pending = asyncio.create_task(agent.send_prompt('unchanged local input', request=QueuePromptRequest('unchanged local input', True)))
        assert await asyncio.to_thread(entered.wait, 5)
        assert agent.controller.prompt_in_flight == 1
        agent.session_id = 'B'
        agent.session_id = 'A'
        release.set()
        with pytest.raises(jsonrpc.InvalidParams):
            await pending
        assert dispatched == []
        assert agent.controller.prompt_in_flight == 0
        assert not agent.controller._deferred_submissions
        await agent.stop()
    asyncio.run(run())
