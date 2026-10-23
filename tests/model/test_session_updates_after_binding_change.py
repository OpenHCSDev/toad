"""A session update that was being validated when its session or process was replaced publishes nothing."""
import asyncio
from acp import schema
from support.agents import RecordedEvents, deliver
from toad.acp.agent_controller import ThreadTaskRunner
from toad.acp.agent_session import ActiveSessionDisposition
from toad.acp.sdk_boundary import ValidateSessionUpdateTask
from toad.core.events import CoreEvent


class HeldValidation(ThreadTaskRunner):
    def __init__(self):
        self.entered, self.release = asyncio.Event(), asyncio.Event()

    async def run(self, task):
        result = await super().run(task)
        self.entered.set()
        await self.release.wait()
        return result


async def test_a_pending_update_is_dropped_after_the_session_or_process_is_replaced(app_agents, tmp_path, monkeypatch):
    agent = app_agents.detached_agent('A')
    emitted = RecordedEvents()
    subscription = agent.events.subscribe(CoreEvent, emitted.receive)
    for replace in ('binding', 'process'):
        validation = HeldValidation()
        monkeypatch.setattr(agent.controller, 'task_runner', validation)
        pending = asyncio.create_task(deliver(agent, {'sessionUpdate': 'available_commands_update',
            'availableCommands': [{'name': 'stale', 'description': 'old source'}]}))
        await validation.entered.wait()
        if replace == 'binding':
            agent.session_id = 'B'
            agent.session_id = 'A'
        else:
            agent.session.close()
            agent.session.disposition = ActiveSessionDisposition(agent.session)
        emitted.clear()
        validation.release.set()
        assert await pending is None
        assert agent.controller.commands == [] and emitted == []
    # A valid notification through the same exposed method publishes normally.
    monkeypatch.undo()
    await deliver(agent, {'sessionUpdate': 'available_commands_update',
        'availableCommands': [{'name': 'current', 'description': 'current source'}]})
    assert agent.controller.commands[0].name == 'current'
    await agent.stop()
    subscription.close()


async def test_comms_facts_survive_validation_workers_and_reach_the_message_route(app_agents, tmp_path):
    from agent_comms.acp_extension import TextRouteUpdate, encode_updates
    from agent_comms.routing import MessageRoute
    from toad.acp.agent_controller import ProcessTaskRunner, ThreadTaskRunner
    from toad.acp.sdk_boundary import (
        AcceptedSessionUpdateValidation, DecodeCommsMetadataTask, RejectedSessionUpdateValidation,
    )
    from toad.render_processes import RenderProcessPool
    from toad.core.events import Update

    route = MessageRoute('first', ('#team',))
    metadata = encode_updates(TextRouteUpdate(route))
    raw = {'sessionUpdate': 'agent_message_chunk',
           'content': {'type': 'text', 'text': 'routed content'}, '_meta': metadata}
    pool = RenderProcessPool(max_workers=1, max_pending=2)
    agent = app_agents.detached_agent('A')
    emitted = RecordedEvents()
    subscription = agent.events.subscribe(CoreEvent, emitted.receive)
    try:
        for owner in (ThreadTaskRunner(), ProcessTaskRunner(pool)):
            accepted = await owner.run(ValidateSessionUpdateTask(
                schema.SessionNotification.model_validate({'sessionId': 'A', 'update': raw}), raw))
            assert isinstance(accepted, AcceptedSessionUpdateValidation)
            assert accepted.updates == (TextRouteUpdate(route),)
            assert await owner.run(DecodeCommsMetadataTask(metadata)) == accepted.updates
            malformed = dict(raw, _meta={'agentComms': {'updates': [{'kind': 'unknown'}]}})
            assert isinstance(await owner.run(ValidateSessionUpdateTask(
                schema.SessionNotification.model_validate({'sessionId': 'A', 'update': malformed}), malformed)),
                              RejectedSessionUpdateValidation)
            agent.controller.task_runner = owner
            emitted.clear()
            await deliver(agent, raw)
            message = next(event for event in emitted if isinstance(event, Update))
            assert message.stream.delivery.route == route
    finally:
        subscription.close()
        await agent.stop()
        await pool.aclose()
