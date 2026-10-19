"""A client request for a session that was replaced has no effect: no file written, no process kept, no permission granted."""
import asyncio
from pathlib import Path
from toad import jsonrpc
from toad.acp.client_session import ClientRequestOwner
from toad.acp.terminal_controller import TerminalSessionRetired
from toad.terminal_execution import TerminalExecution


async def rpc(agent, method, session='before', **params):
    return await agent.server.call({'jsonrpc': '2.0', 'id': 1, 'method': method,
                                   'params': {'sessionId': session, **params}})


async def test_files_and_processes_requested_for_a_replaced_session_are_refused(app_agents, tmp_path):
    agent = app_agents.detached_agent('before')
    assert (await rpc(agent, 'fs/write_text_file', path='owned.txt', content='one\ntwo\nthree'))['result'] == {}
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


async def test_a_terminal_that_starts_after_its_session_was_replaced_is_closed(app_agents, tmp_path, monkeypatch):
    agent = app_agents.detached_agent('before')
    entered, release = asyncio.Event(), asyncio.Event()
    real_start = TerminalExecution.start
    executions = []
    async def pending_start(execution):
        executions.append(execution)
        entered.set()
        await release.wait()
        await real_start(execution)
    monkeypatch.setattr(TerminalExecution, 'start', pending_start)
    replaced = agent.controller.terminals
    request = asyncio.create_task(rpc(agent, 'terminal/create', command='sh', args=['-c', 'sleep 30']))
    await entered.wait()
    agent.session_id = 'after'
    await replaced.close()
    release.set()
    response = await request
    assert response['error']['code'] == -32602
    assert not replaced.executions and not agent.controller.terminals.executions
    try:
        await replaced.create(executions[0].command, None)
    except TerminalSessionRetired:
        pass
    else:
        raise AssertionError('Retired terminal controller started another process')
    await agent.stop()


async def test_a_new_client_request_registers_by_declaration(app_agents, tmp_path):
    class EchoClientRequestOwner(ClientRequestOwner):
        @jsonrpc.expose('test/session_echo')
        def echo(self, sessionId: str):
            self.session_request(sessionId)
            return {'sessionId': sessionId}
    agent = app_agents.detached_agent('before')
    assert (await rpc(agent, 'test/session_echo'))['result'] == {'sessionId': 'before'}
    assert (await rpc(agent, 'test/session_echo', session='retired'))['error']['code'] == -32602
    await agent.stop()


async def test_a_terminal_wait_is_refused_when_its_owner_was_replaced_even_if_the_session_id_returns(app_agents, tmp_path, monkeypatch):
    agent = app_agents.detached_agent('before')
    created = await rpc(agent, 'terminal/create', command='sh', args=['-c', 'sleep 30'])
    terminal_id = created['result']['terminalId']
    replaced = agent.controller.terminals
    execution = replaced.require(terminal_id)
    entered, release = asyncio.Event(), asyncio.Event()
    real_wait = replaced.wait
    async def pending_wait(terminal_id):
        entered.set()
        result = await real_wait(terminal_id)
        await release.wait()
        return result
    monkeypatch.setattr(replaced, 'wait', pending_wait)
    waiting = asyncio.create_task(rpc(agent, 'terminal/wait_for_exit', terminalId=terminal_id))
    await entered.wait()
    disposition = agent.session.disposition
    agent.session_id = 'after'
    agent.session_id = 'before'
    assert agent.session.disposition is disposition
    await replaced.close()
    release.set()
    result = await waiting
    assert result['error']['code'] == -32602
    assert 'result' not in result
    assert not replaced.executions and not agent.controller.terminals.executions
    await agent.stop()
