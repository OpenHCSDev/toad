"""A session update that was being validated when its session or process was replaced publishes nothing."""
from acp import schema
from support.agents import RecordedEvents, deliver
from toad.acp.sdk_boundary import ValidateSessionUpdateTask
from toad.core.events import CoreEvent






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
