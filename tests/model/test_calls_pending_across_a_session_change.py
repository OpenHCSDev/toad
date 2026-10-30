"""A handshake, authentication, mode, new or load call that returns after the session binding changed is rejected."""
import asyncio
from collections.abc import Callable, Coroutine

from acp.exceptions import RequestError
from acp.schema import SessionConfigOptionSelect, SessionConfigSelectOption

from support.agents import AppAgents
from toad.acp.agent import Agent


async def test_pending_session_calls_reject_a_binding_that_was_replaced(app_agents: AppAgents) -> None:
    calls: tuple[tuple[Callable[[Agent], Coroutine[object, object, str | None]], str], ...] = (
        (lambda agent: agent.session.initialize(), 'initialize'),
        (lambda agent: agent.session.authenticate('terminal'), 'authenticate'),
        (lambda agent: agent.set_mode('late'), 'set_config_option'),
        (lambda agent: agent.session.new(), 'new_session'),
        (lambda agent: agent.session.load(), 'load_session'),
    )
    for call, sdk_name in calls:
        agent = app_agents.detached_agent('first')
        agent.configuration.receive([SessionConfigOptionSelect(
            id='mode', name='Mode', category='mode', type='select', current_value='normal',
            options=[SessionConfigSelectOption(value='normal', name='Normal'),
                     SessionConfigSelectOption(value='late', name='Late')],
        )])
        entered, release = asyncio.Event(), asyncio.Event()
        class PendingConnection:
            pass
        async def pending(*args: object, **kwargs: object) -> None:
            entered.set()
            await release.wait()
        setattr(PendingConnection, sdk_name, staticmethod(pending))
        agent.process.connection = PendingConnection()
        binding = agent.controller.session
        task = asyncio.create_task(call(agent))
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
            assert response is not None and 'retired session' in response
        assert agent.session_id == 'first'
        assert not agent.session.capabilities.load_session
        assert not agent.presentation.auth_methods
        assert not agent.session.ready
        agent.process.connection = None
        await agent.stop()
