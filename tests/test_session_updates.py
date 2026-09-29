"""Registered notification authority uses the real SDK and actual binding identities."""
import asyncio
from toad.acp.agent import Agent
from toad.acp.agent_process import ActiveProcessDisposition
from toad.acp.session_updates import SessionUpdateEffect
from toad.render_tasks import ValidateSessionUpdateTask


def test_pending_notification_cannot_publish_after_process_or_session_return(tmp_path, monkeypatch):
    async def run():
        agent = Agent(tmp_path, {'name': 'updates', 'run_command': {'*': 'true'}}, 'A')
        emitted = []
        agent.post_message = emitted.append
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
                agent.process.close()
                agent.process.disposition = ActiveProcessDisposition()
            emitted.clear()
            release.set()
            assert await pending is None
            assert agent.controller.commands == [] and emitted == []
        # A valid notification through the same exposed method publishes normally.
        monkeypatch.undo()
        await agent.server.call({'jsonrpc': '2.0', 'method': 'session/update',
            'params': {'sessionId': 'A', 'update': {'sessionUpdate': 'available_commands_update',
            'availableCommands': [{'name': 'current', 'description': 'current source'}]}}})
        assert agent.controller.commands[0]['name'] == 'current'
        await agent.stop()
    asyncio.run(run())


def test_new_update_effect_owns_behavior_without_dispatch_or_roster_edit():
    class AddedEffect(SessionUpdateEffect, declared_name='test_declaration_effect'):
        def apply(self, agent, route):
            agent.append((self.update['value'], route))
    raw = {'sessionUpdate': AddedEffect.declared_name, 'value': 'owned'}
    effect = SessionUpdateEffect.from_wire(raw)
    assert effect.update is raw
    assert SessionUpdateEffect.decode(AddedEffect.declared_name) is AddedEffect
    result = []
    effect.apply(result, 'route')
    assert result == [('owned', 'route')]
