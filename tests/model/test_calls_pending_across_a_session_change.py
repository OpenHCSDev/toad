"""A handshake, authentication, mode, new or load call that returns after the session binding changed is rejected."""
import asyncio

from support.agents import detached
from toad import jsonrpc
from toad.acp import api


async def test_pending_session_calls_reject_a_binding_that_was_replaced(tmp_path, monkeypatch):
    for method, api_name, result, args in (
        ('initialize', 'initialize', {'agentCapabilities': {'loadSession': True}, 'authMethods': [{'id': 'late'}]}, ()),
        ('authenticate', 'authenticate', {}, ('terminal',)),
        ('set_mode', 'session_set_mode', {}, ('late',)),
        ('new', 'session_new', {'sessionId': 'late-new'}, ()),
        ('load', 'session_load', {}, ()),
    ):
        agent = detached(tmp_path, 'first')
        entered, release = asyncio.Event(), asyncio.Event()
        class Pending:
            async def wait(self):
                entered.set()
                await release.wait()
                return result
        monkeypatch.setattr(api, api_name, lambda *a, **k: Pending())
        binding = agent.controller.session
        task = asyncio.create_task(getattr(agent.session, method)(*args))
        await entered.wait()
        agent.session_id = 'replacement'
        agent.session_id = 'first'
        assert agent.controller.session is not binding
        release.set()
        try:
            response = await task
        except jsonrpc.InvalidParams:
            pass
        else:
            # Mode's existing public failure contract returns actionable feedback.
            assert method == 'set_mode' and 'retired session' in response
        assert agent.session_id == 'first'
        assert not agent.session.capabilities.load_session
        assert not agent.presentation.auth_methods
        assert not agent.session.ready
        await agent.stop()
