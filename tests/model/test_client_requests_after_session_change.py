"""A client request for a session that was replaced has no effect: no file written, no process kept, no permission granted."""
import asyncio
import pytest
from acp import schema
from acp.exceptions import RequestError
from toad.acp.terminal_controller import TerminalSessionRetired
from toad.terminal_execution import TerminalExecution


async def test_files_and_processes_requested_for_a_replaced_session_are_refused(app_agents, tmp_path):
    agent = app_agents.detached_agent('before')
    assert agent.files.write_text_file('before', 'owned.txt', 'one\ntwo\nthree') == schema.WriteTextFileResponse()
    assert agent.files.read_text_file('before', 'owned.txt', 2, 1).content == 'two'
    agent.session_id = 'after'
    with pytest.raises(RequestError) as refused:
        agent.files.write_text_file('before', 'owned.txt', 'stale overwrite')
    assert refused.value.code == -32602
    assert (tmp_path/'owned.txt').read_text() == 'one\ntwo\nthree'
    with pytest.raises(RequestError) as refused:
        await agent.controller.terminal_create('before', 'sh', None, ['-c', 'exit 0'])
    assert refused.value.code == -32602
    assert not agent.controller.terminals.executions
    cancelled = await agent.permissions.request_permission(
        'before', [], schema.ToolCallUpdate(tool_call_id='retired'))
    assert cancelled.outcome == schema.DeniedOutcome(outcome='cancelled')
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
    request = asyncio.create_task(agent.controller.terminal_create('before', 'sh', None, ['-c', 'sleep 30']))
    await entered.wait()
    agent.session_id = 'after'
    await replaced.close()
    release.set()
    with pytest.raises(RequestError) as refused:
        await request
    assert refused.value.code == -32602
    assert not replaced.executions and not agent.controller.terminals.executions
    with pytest.raises(TerminalSessionRetired):
        await replaced.create(executions[0].command, None)
    await agent.stop()


async def test_a_terminal_wait_is_refused_when_its_owner_was_replaced_even_if_the_session_id_returns(app_agents, tmp_path, monkeypatch):
    agent = app_agents.detached_agent('before')
    created = await agent.controller.terminal_create('before', 'sh', None, ['-c', 'sleep 30'])
    terminal_id = created.terminal_id
    replaced = agent.controller.terminals
    entered, release = asyncio.Event(), asyncio.Event()
    real_wait = replaced.wait
    async def pending_wait(terminal_id):
        entered.set()
        result = await real_wait(terminal_id)
        await release.wait()
        return result
    monkeypatch.setattr(replaced, 'wait', pending_wait)
    waiting = asyncio.create_task(agent.controller.terminal_wait_for_exit('before', terminal_id))
    await entered.wait()
    disposition = agent.session.disposition
    agent.session_id = 'after'
    agent.session_id = 'before'
    assert agent.session.disposition is disposition
    await replaced.close()
    release.set()
    with pytest.raises(RequestError) as refused:
        await waiting
    assert refused.value.code == -32602
    assert not replaced.executions and not agent.controller.terminals.executions
    await agent.stop()
