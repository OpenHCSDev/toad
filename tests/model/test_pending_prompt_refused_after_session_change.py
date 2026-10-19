"""A prompt still being built is refused, and never sent, when the session changes and returns meanwhile."""
import asyncio
import threading
from agent_comms.acp_extension import QueuePromptRequest
from toad.acp import agent_controller


async def test_pending_prompt_build_is_refused_when_the_session_changes_and_returns(app_agents, monkeypatch):
    agent = app_agents.detached_agent('A', identity='prompt-session')
    entered, release = threading.Event(), threading.Event()
    real_build = agent_controller.build_prompt
    def pending_build(project, text):
        entered.set()
        assert release.wait(5), 'Test failed to release resource preparation'
        return real_build(project, text)
    dispatched = []
    monkeypatch.setattr(agent_controller, 'build_prompt', pending_build)
    async def recorded_prompt(agent, content, metadata, require):
        require()
        dispatched.append(content)
    monkeypatch.setattr(agent.process, 'prompt', recorded_prompt)
    pending = asyncio.create_task(agent.send_prompt('unchanged local input', request=QueuePromptRequest('unchanged local input', True)))
    assert await asyncio.to_thread(entered.wait, 5)
    assert agent.controller.prompt_in_flight == 1
    sending_now = asyncio.create_task(agent.controller.send_now())
    await asyncio.sleep(0)
    agent.session_id = 'B'
    agent.session_id = 'A'
    release.set()
    # The retired prompt's controller refuses it at the write and reports no stop reason.
    assert await pending is None
    assert await sending_now is False
    assert dispatched == []
    assert agent.controller.prompt_in_flight == 0
    assert not agent.controller._deferred_submissions
    await agent.stop()
