"""Session effects use actual RPC registration, filesystem and subprocess owners."""
import asyncio
from pathlib import Path
from toad import jsonrpc
from toad.acp.agent import Agent
from toad.acp.client_session import ClientRequestOwner
from toad.acp.terminal_controller import TerminalSessionRetired
from toad.terminal_execution import TerminalExecution


def make_agent(root):
    return Agent(root, {'name': 'client-session', 'run_command': {'*': 'true'}}, 'before')

async def rpc(agent, method, session='before', **params):
    return await agent.server.call({'jsonrpc': '2.0', 'id': 1, 'method': method,
                                   'params': {'sessionId': session, **params}})


def test_session_replacement_rejects_files_without_side_effects(tmp_path):
    async def run():
        agent = make_agent(tmp_path)
        assert (await rpc(agent, 'fs/write_text_file', path='owned.txt', content='one\ntwo\nthree'))['result'] is None
        assert (await rpc(agent, 'fs/read_text_file', path='owned.txt', line=2, limit=1))['result'] == {'content': 'two'}
        agent.session_id = 'after'
        refused = await rpc(agent, 'fs/write_text_file', path='owned.txt', content='stale overwrite')
        assert refused['error']['code'] == -32602
        assert (tmp_path/'owned.txt').read_text() == 'one\ntwo\nthree'
        assert (await rpc(agent, 'terminal/create', command='sh', args=['-c', 'exit 0']))['error']['code'] == -32602
        assert not agent.controller.terminals.executions
        cancelled = await rpc(agent, 'session/request_permission', options=[], toolCall={'toolCallId': 'retired'})
        assert cancelled['result']['outcome'] == {'outcome': 'cancelled'}
        await agent.stop()
    asyncio.run(run())


def test_retired_terminal_start_closes_actual_late_spawn(tmp_path, monkeypatch):
    async def run():
        agent = make_agent(tmp_path)
        entered, release = asyncio.Event(), asyncio.Event()
        real_start = TerminalExecution.start
        executions = []
        async def pending_start(execution, width, height):
            executions.append(execution)
            entered.set()
            await release.wait()
            await real_start(execution, width, height)
        monkeypatch.setattr(TerminalExecution, 'start', pending_start)
        original = agent.controller.terminals
        request = asyncio.create_task(rpc(agent, 'terminal/create', command='sh', args=['-c', 'sleep 30']))
        await entered.wait()
        agent.session_id = 'after'
        await original.close()
        release.set()
        response = await request
        assert response['error']['code'] == -32602
        assert executions[0]._process.returncode is not None
        assert not original.executions and not agent.controller.terminals.executions
        try:
            await original.create(executions[0]._command, None)
        except TerminalSessionRetired:
            pass
        else:
            raise AssertionError('Retired terminal controller admitted another process')
        await agent.stop()
    asyncio.run(run())


def test_new_client_capability_registers_without_roster_or_agent_edit(tmp_path):
    class EchoClientRequestOwner(ClientRequestOwner):
        @jsonrpc.expose('test/session_echo')
        def echo(self, sessionId: str):
            self.session_request(sessionId)
            return {'sessionId': sessionId}
    async def run():
        agent = make_agent(tmp_path)
        assert (await rpc(agent, 'test/session_echo'))['result'] == {'sessionId': 'before'}
        assert (await rpc(agent, 'test/session_echo', session='retired'))['error']['code'] == -32602
        await agent.stop()
    asyncio.run(run())


def test_terminal_wait_rejects_same_session_return_after_owner_replacement(tmp_path, monkeypatch):
    async def run():
        agent = make_agent(tmp_path)
        created = await rpc(agent, 'terminal/create', command='sh', args=['-c', 'sleep 30'])
        terminal_id = created['result']['terminalId']
        original = agent.controller.terminals
        execution = original.require(terminal_id)
        entered, release = asyncio.Event(), asyncio.Event()
        real_wait = original.wait
        async def pending_wait(terminal_id):
            entered.set()
            result = await real_wait(terminal_id)
            await release.wait()
            return result
        monkeypatch.setattr(original, 'wait', pending_wait)
        waiting = asyncio.create_task(rpc(agent, 'terminal/wait_for_exit', terminalId=terminal_id))
        await entered.wait()
        disposition = agent.process.disposition
        agent.session_id = 'after'
        agent.session_id = 'before'
        assert agent.process.disposition is disposition
        await original.close()
        release.set()
        result = await waiting
        assert result['error']['code'] == -32602
        assert 'result' not in result
        assert execution._process.returncode is not None
        assert not original.executions and not agent.controller.terminals.executions
        await agent.stop()
    asyncio.run(run())
