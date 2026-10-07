"""Registered notification authority uses the real SDK and actual binding identities."""
import asyncio
from toad.acp.agent import Agent
from toad.acp.agent_session import ActiveSessionDisposition
from toad.agent_schema import AgentDefinition
from toad.acp.sdk_boundary import ValidateSessionUpdateTask


def test_pending_notification_cannot_publish_after_process_or_session_return(tmp_path, monkeypatch):
    async def run():
        agent = Agent(tmp_path, AgentDefinition('updates', 'updates', {'*': 'true'}), 'A')
        emitted = []
        subscription = agent.events.subscribe(lambda event, source: emitted.append(event))
        for replace in ('binding', 'process'):
            entered, release = asyncio.Event(), asyncio.Event()
            async def validation(session_id, update, metadata):
                result = ValidateSessionUpdateTask(session_id, update, metadata).execute()
                entered.set()
                await release.wait()
                return result
            monkeypatch.setattr(agent.controller, 'validate', validation)
            pending = asyncio.create_task(agent.server.call({'jsonrpc': '2.0', 'method': 'session/update',
                'params': {'sessionId': 'A', 'update': {'sessionUpdate': 'available_commands_update',
                'availableCommands': [{'name': 'stale', 'description': 'old source'}]}}}))
            await entered.wait()
            if replace == 'binding':
                agent.session_id = 'B'
                agent.session_id = 'A'
            else:
                agent.session.close()
                agent.session.disposition = ActiveSessionDisposition()
            emitted.clear()
            release.set()
            assert await pending is None
            assert agent.controller.commands == [] and emitted == []
        # A valid notification through the same exposed method publishes normally.
        monkeypatch.undo()
        await agent.server.call({'jsonrpc': '2.0', 'method': 'session/update',
            'params': {'sessionId': 'A', 'update': {'sessionUpdate': 'available_commands_update',
            'availableCommands': [{'name': 'current', 'description': 'current source'}]}}})
        assert agent.controller.commands[0].name == 'current'
        await agent.stop()
        subscription.close()
    asyncio.run(run())


def test_comms_facts_cross_original_validation_workers_and_reach_message_route(tmp_path):
    from agent_comms.acp_extension import TextRouteUpdate, encode_updates
    from agent_comms.routing import MessageRoute
    from toad.acp.agent_controller import ApplicationValidationOwner, HeadlessValidationOwner
    from toad.acp.sdk_boundary import (
        AcceptedSessionUpdateValidation, DecodeCommsMetadataTask, RejectedSessionUpdateValidation,
    )
    from toad.render_processes import RenderProcessPool
    from toad.core.events import Update

    async def run():
        route = MessageRoute('original', ('#team',))
        metadata = encode_updates(TextRouteUpdate(route))
        raw = {'sessionUpdate': 'agent_message_chunk',
               'content': {'type': 'text', 'text': 'original routed content'}, '_meta': metadata}
        pool = RenderProcessPool(max_workers=1, max_pending=2)
        agent = Agent(tmp_path, AgentDefinition('updates', 'updates', {'*': 'true'}), 'A')
        emitted = []
        subscription = agent.events.subscribe(lambda event, source: emitted.append(event))
        try:
            for owner in (HeadlessValidationOwner(), ApplicationValidationOwner(pool)):
                accepted = await owner.validate(ValidateSessionUpdateTask('A', raw))
                assert isinstance(accepted, AcceptedSessionUpdateValidation)
                assert accepted.updates == (TextRouteUpdate(route),)
                assert await owner.validate(DecodeCommsMetadataTask(metadata)) == accepted.updates
                malformed = dict(raw, _meta={'agentComms': {'updates': [{'kind': 'unknown'}]}})
                assert isinstance(await owner.validate(ValidateSessionUpdateTask('A', malformed)),
                                  RejectedSessionUpdateValidation)
                agent.controller.validation = owner
                emitted.clear()
                await agent.server.call({'jsonrpc': '2.0', 'method': 'session/update',
                    'params': {'sessionId': 'A', 'update': raw}})
                message = next(event for event in emitted if isinstance(event, Update))
                assert message.stream.delivery.route == route
        finally:
            subscription.close()
            await agent.stop()
            await pool.aclose()
    asyncio.run(run())
