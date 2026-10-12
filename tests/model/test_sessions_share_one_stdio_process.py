"""Sessions attached to one stdio agent process share its connection; closing one session, or one the agent refused, leaves the others and the process running."""
import asyncio

import pytest

from acp.schema import AvailableCommand, AvailableCommandsUpdate
from agent_comms.comms import wire
from support.shared_stdio import stdio_agent_definition, threads_owned_here
from toad.acp.agent import Agent


@pytest.fixture
def attachment_scope(tmp_path, monkeypatch):
    root = tmp_path / 'wire'
    project = tmp_path / 'project'
    project.mkdir()
    monkeypatch.setenv('AGENT_COMMS_ROOT', str(root))
    monkeypatch.setenv('AGENT_COMMS_AGENT_MODELS', 'test/one')
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'state'))
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'config'))
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'data'))
    for key in ('AGENT_COMMS_THREAD', 'AGENT_COMMS_MANAGED', 'PI_AGENT_ID', 'PI_PARENT_ID'):
        monkeypatch.delenv(key, raising=False)
    return project, stdio_agent_definition(), wire(root)


async def test_closing_one_session_leaves_the_others_on_the_shared_process(attachment_scope):
    project, definition, comms = attachment_scope
    permissions = []
    alpha, beta, reopened = [Agent(project, definition, name) for name in ('alpha', 'beta', 'alpha')]
    shared = None
    try:
        async with threads_owned_here(comms, project) as owner:
            await alpha.start()
            async with asyncio.timeout(10):
                await alpha.session.settled.wait()
            assert alpha.ready
            shared = alpha.process
            child = shared.process
            handshake = shared.initialization
            assert handshake.agent_capabilities.session_capabilities.close is not None
            await beta.start((shared,))
            async with asyncio.timeout(10):
                await beta.session.settled.wait()
            assert beta.ready and beta.process is shared
            assert shared.process is child and shared.initialization is handshake
            assert shared.sessions == {alpha.session, beta.session}
            assert shared.recipient({'params': {'sessionId': 'alpha'}}) is alpha
            assert shared.recipient({'params': {'sessionId': 'beta'}}) is beta
            assert shared.recipient({'params': {'sessionId': 'foreign'}}) is None
            assert not shared.accepts_attachment(beta, shared.env, shared.cwd, shared.route_selection)
            changed_env = dict(shared.env, SHARED_TRANSPORT_FOREIGN_ENV='different')
            assert not shared.accepts_attachment(reopened, changed_env, shared.cwd, shared.route_selection)
            assert not shared.accepts_attachment(reopened, shared.env, str(project.parent), shared.route_selection)
            identities = {name: comms.registry.require(name).require_process() for name in ('alpha', 'beta')}
            for name in ('alpha', 'beta'):
                selected = next(iter(owner._runtime.clients[name]))
                permissions.append(asyncio.create_task(owner._runtime.request_permission(
                    name, selected, {'toolCall': {'toolCallId': f'{name}-owned'},
                                     'options': [{'optionId': 'reject', 'name': 'Reject',
                                                  'kind': 'reject_once'}]})))
            async with asyncio.timeout(5):
                while not alpha.permissions.pending or not beta.permissions.pending:
                    await asyncio.sleep(0)
            await alpha.stop()
            async with asyncio.timeout(5):
                answer = await permissions[0]
                assert answer is None or answer['outcome'] == 'cancelled'
            assert not permissions[1].done() and beta.permissions.pending
            beta.permissions.cancel()
            async with asyncio.timeout(5):
                assert (await permissions[1])['outcome'] == 'cancelled'
            assert shared.sessions == {beta.session} and beta.ready
            assert shared.process is child and shared.runner is not None and not shared.runner.done()
            assert shared.recipient({'params': {'sessionId': 'alpha'}}) is None
            await owner._runtime.session_update(session_id='beta', update=AvailableCommandsUpdate(
                session_update='available_commands_update',
                available_commands=[AvailableCommand(name='still_attached', description='Beta command')]))
            async with asyncio.timeout(5):
                while not beta.controller.commands:
                    await asyncio.sleep(0)
            assert beta.controller.commands[0].name == 'still_attached'
            await reopened.start((shared,))
            async with asyncio.timeout(10):
                await reopened.session.settled.wait()
            assert reopened.ready and reopened.process is shared
            assert shared.initialization is handshake and shared.process is child
            await reopened.stop()
            assert beta.ready and shared.sessions == {beta.session}
            assert {name: comms.registry.require(name).require_process() for name in identities} == identities
            assert all(identity.alive() for identity in identities.values())
    finally:
        for agent in (alpha, beta, reopened):
            await agent.stop()
        await asyncio.gather(*permissions, return_exceptions=True)
    assert shared is not None and shared.process is None and not shared.sessions
    assert not shared.custody._exit_callbacks


async def test_stopping_a_session_the_agent_refused_leaves_the_shared_process(attachment_scope):
    project, definition, comms = attachment_scope
    alpha, refused = Agent(project, definition, 'alpha'), Agent(project, definition, 'never-declared')
    shared = None
    try:
        async with threads_owned_here(comms, project):
            await alpha.start()
            async with asyncio.timeout(10):
                await alpha.session.settled.wait()
            assert alpha.ready
            shared = alpha.process
            await refused.start((shared,))
            async with asyncio.timeout(10):
                await refused.session.settled.wait()
            assert not refused.ready and refused.process is shared
            assert shared.sessions == {alpha.session, refused.session}

            # The agent holds no session for it, so there is nothing to ask it to close.
            await refused.stop()

            assert alpha.ready and shared.sessions == {alpha.session}
            assert shared.runner is not None and not shared.runner.done()
    finally:
        for agent in (alpha, refused):
            await agent.stop()
    assert shared is not None and shared.process is None and not shared.sessions
