"""Actual stdio ACP attachments share launch custody, not session authority."""
import asyncio
import os
import shlex
import sys
import pytest
from contextlib import asynccontextmanager

from acp.schema import AvailableCommand, AvailableCommandsUpdate
from agent_comms.acp import CommsAgent
from agent_comms.comms import wire
from toad.acp.agent import Agent
from toad.agent_schema import AgentDefinition


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
    command = shlex.join([sys.executable, '-c', '''
import asyncio
from agent_comms.acp import CommsClient
from agent_comms.comms import wire
from acp import run_agent
async def main():
    client = CommsClient(wire(), auto_wake=False, use_unstable_protocol=True)
    try:
        await run_agent(client, use_unstable_protocol=client.use_unstable_protocol)
    finally:
        await client.shutdown()
asyncio.run(main())
'''])
    definition = AgentDefinition('real-attachments', 'Real attachments', {'*': command})

    return project, definition, wire(root)


@asynccontextmanager
async def original_owner(scope):
    project, definition, comms = scope
    owner = CommsAgent(comms, runtime_enabled=True, auto_wake=False)
    try:
        for name in ('alpha', 'beta'):
            thread = comms.threads.claim_thread(name, tags=frozenset({'acp'}),
                                               worktree=str(project), start_at_latest=True)
            comms.threads.restore_stopped(comms.registry.snapshot(), (name,))
            thread = comms.owners.acquire_thread(name, owner_pid=os.getpid())
            await owner.sessions.bind_owned(thread, name)
        yield owner
    finally:
        await owner.shutdown()


def test_shared_stdio_closes_only_its_original_session(attachment_scope):
    project, definition, comms = attachment_scope
    async def run():
        owner_context = original_owner(attachment_scope)
        owner = await owner_context.__aenter__()
        alpha, beta, reopened = [Agent(project, definition, name)
                                 for name in ('alpha', 'beta', 'alpha')]
        original = None
        permissions = []
        try:
            await alpha.start()
            async with asyncio.timeout(10):
                await alpha.session.settled.wait()
            assert alpha.ready
            original = alpha.process
            child = original.process
            handshake = original.initialization
            assert handshake.agent_capabilities.session_capabilities.close is not None
            await beta.start((original,))
            async with asyncio.timeout(10):
                await beta.session.settled.wait()
            assert beta.ready and beta.process is original
            assert original.process is child and original.initialization is handshake
            assert original.sessions == {alpha.session, beta.session}
            assert original.recipient({'params': {'sessionId': 'alpha'}}) is alpha
            assert original.recipient({'params': {'sessionId': 'beta'}}) is beta
            assert original.recipient({'params': {'sessionId': 'foreign'}}) is None
            assert not original.accepts_attachment(beta, original.env, original.cwd, original.route_selection)
            changed_env = dict(original.env, SHARED_TRANSPORT_FOREIGN_ENV='different')
            assert not original.accepts_attachment(reopened, changed_env, original.cwd, original.route_selection)
            assert not original.accepts_attachment(reopened, original.env, str(project.parent), original.route_selection)
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
            assert original.sessions == {beta.session} and beta.ready
            assert original.process is child and original.runner is not None and not original.runner.done()
            assert original.recipient({'params': {'sessionId': 'alpha'}}) is None
            await owner._runtime.session_update(session_id='beta', update=AvailableCommandsUpdate(
                session_update='available_commands_update',
                available_commands=[AvailableCommand(name='still_attached', description='Original beta')]))
            async with asyncio.timeout(5):
                while not beta.controller.commands:
                    await asyncio.sleep(0)
            assert beta.controller.commands[0].name == 'still_attached'
            await reopened.start((original,))
            async with asyncio.timeout(10):
                await reopened.session.settled.wait()
            assert reopened.ready and reopened.process is original
            assert original.initialization is handshake and original.process is child
            await reopened.stop()
            assert beta.ready and original.sessions == {beta.session}
            assert {name: comms.registry.require(name).require_process() for name in identities} == identities
            assert all(identity.alive() for identity in identities.values())
        finally:
            for agent in (alpha, beta, reopened):
                await agent.stop()
            await asyncio.gather(*permissions, return_exceptions=True)
            await owner_context.__aexit__(None, None, None)
        assert original is not None and original.process is None and not original.sessions
        assert not original.custody._exit_callbacks
    asyncio.run(run())


def test_real_workspace_tab_uses_retained_operational_connection(attachment_scope):
    from runtime_fixture import ToadApp
    from toad.screens.main import MainScreen
    project, definition, comms = attachment_scope

    async def ready(agent):
        async with asyncio.timeout(10):
            await agent.session.settled.wait()
        assert agent.ready

    async def run():
        async with original_owner(attachment_scope):
            app = ToadApp(project_dir=str(project), agent_data=definition,
                          agent_session_id='alpha')
            async with app.run_test(size=(110, 36)) as pilot:
                async with asyncio.timeout(10):
                    while (source := app.selected_session).presentation.operational_agent is None:
                        await pilot.pause()
                first = source.presentation.operational_agent
                await ready(first)
                connection = first.process
                owner_mode = app.selected_mode
                details = await app.session_navigation.new(
                    lambda: MainScreen(project, definition, 'beta'))
                second_source = app.workspace_sessions.require(details.mode_name)
                async with asyncio.timeout(10):
                    while second_source.presentation.operational_agent is None:
                        await pilot.pause()
                second = second_source.presentation.operational_agent
                await ready(second)
                assert second.process is connection
                await app.select_session(owner_mode)
                assert source.presentation.operational_agent is first
                await app.session_navigation.close(details.mode_name)
                assert first.ready and connection.sessions == {first.session}
                assert connection.process is not None and not connection.runner.done()
                assert app._exception is None
            assert connection.process is None and not connection.sessions
    asyncio.run(run())
