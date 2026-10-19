"""A handshake, authentication, mode, new or load call that returns after the session binding changed is rejected."""
import asyncio

from acp.exceptions import RequestError


async def test_pending_session_calls_reject_a_binding_that_was_replaced(app_agents, tmp_path):
    for method, sdk_name, args in (
        ('initialize', 'initialize', ()),
        ('authenticate', 'authenticate', ('terminal',)),
        ('set_mode', 'set_session_mode', ('late',)),
        ('new', 'new_session', ()),
        ('load', 'load_session', ()),
    ):
        agent = app_agents.detached_agent('first')
        entered, release = asyncio.Event(), asyncio.Event()
        class PendingConnection:
            pass
        async def pending(*a, **k):
            entered.set()
            await release.wait()
        setattr(PendingConnection, sdk_name, staticmethod(pending))
        agent.process.connection = PendingConnection()
        binding = agent.controller.session
        task = asyncio.create_task(getattr(agent.session, method)(*args))
        await entered.wait()
        agent.session_id = 'replacement'
        agent.session_id = 'first'
        assert agent.controller.session is not binding
        release.set()
        try:
            response = await task
        except RequestError as error:
            assert error.code == -32602
        else:
            # Mode's existing public failure contract returns actionable feedback.
            assert method == 'set_mode' and 'retired session' in response
        assert agent.session_id == 'first'
        assert not agent.session.capabilities.load_session
        assert not agent.presentation.auth_methods
        assert not agent.session.ready
        agent.process.connection = None
        await agent.stop()
