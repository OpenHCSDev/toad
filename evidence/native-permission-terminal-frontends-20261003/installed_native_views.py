"""Changed original views through registered ACP requests and real native resources."""
import asyncio
import json
import os
from pathlib import Path
import signal
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests'))
sys.path.insert(0, str(ROOT / 'evidence/headless-agent-services-u2-20261003'))
from installed_services import InstalledApp
from l0a_native_installed_pilot import main, until
from native_terminal_retention_pilot import pty_masters
from toad.screens.permissions import PermissionReview
from toad.widgets.terminal_tool import TerminalTool


async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    started = time.monotonic()
    evidence = Path(os.environ['L0A_EVIDENCE'])
    view = app.selected_session.conversation
    process = agent.process.process
    initial_masters = pty_masters()
    request_id = 0

    async def rpc(method, **params):
        nonlocal request_id
        request_id += 1
        result = await agent.server.call({'jsonrpc': '2.0', 'id': request_id,
            'method': method, 'params': {'sessionId': agent.session_id, **params}})
        assert 'error' not in result, result
        return result['result']

    def frame():
        return '\n'.join(strip.text for strip in app.screen._compositor.render_strips())

    options = [{'optionId': 'allow', 'name': 'Allow once', 'kind': 'allow_once'},
               {'optionId': 'reject', 'name': 'Reject', 'kind': 'reject_once'}]
    diff = {'toolCallId': 'native-diff', 'title': 'NATIVE_PERMISSION', 'kind': 'edit',
            'content': [{'type': 'diff', 'path': str(agent.project_root_path / 'private.txt'),
                         'oldText': 'old private value', 'newText': 'NATIVE_PERMISSION_NEW'}]}
    permission = asyncio.create_task(rpc('session/request_permission', options=options, toolCall=diff))
    await until(pilot, lambda: isinstance(app.screen, PermissionReview))
    await until(pilot, lambda: 'NATIVE_PERMISSION_NEW' in frame() and 'Allow' in frame())
    app.save_screenshot('permission-review.svg', path=str(evidence))
    await pilot.press('a')
    assert (await permission)['outcome'] == {'outcome': 'selected', 'optionId': 'allow'}

    pending = asyncio.create_task(rpc('session/request_permission', options=options,
                                    toolCall={**diff, 'toolCallId': 'native-retained-diff'}))
    await until(pilot, lambda: isinstance(app.screen, PermissionReview))
    original_request, = agent.permissions.pending
    future = original_request.future
    binding = agent.controller.surface
    agent.detach_surface(view)
    await until(pilot, lambda: not isinstance(app.screen, PermissionReview))
    assert original_request.pending and original_request.future is future
    view.bind_agent(agent)
    await until(pilot, lambda: isinstance(app.screen, PermissionReview))
    await until(pilot, lambda: 'NATIVE_PERMISSION_NEW' in frame())
    assert agent.controller.surface is not binding
    assert agent.permissions.pending == (original_request,)
    assert original_request.future is future
    await pilot.press('r')
    assert (await pending)['outcome'] == {'outcome': 'selected', 'optionId': 'reject'}

    inline = asyncio.create_task(rpc('session/request_permission', options=options,
        toolCall={'toolCallId': 'native-inline', 'title': 'NATIVE_INLINE_PERMISSION',
                  'kind': 'execute', 'content': [{'type': 'content', 'content': {
                      'type': 'text', 'text': 'NATIVE_INLINE_PREVIEW'}}]}))
    await until(pilot, lambda: 'NATIVE_INLINE_PERMISSION' in frame())
    app.save_screenshot('inline-permission.svg', path=str(evidence))
    await pilot.press('a')
    assert (await inline)['outcome'] == {'outcome': 'selected', 'optionId': 'allow'}
    assert not agent.permissions.pending

    completions = []
    for text, code in [('NATIVE_SUCCESS', 0), ('NATIVE_NONZERO', 7)]:
        terminal_id = (await rpc('terminal/create', command='sh',
            args=['-c', f"printf '{text}\\n'; exit {code}"]))['terminalId']
        execution = agent.controller.terminals.require(terminal_id)
        result = await rpc('terminal/wait_for_exit', terminalId=terminal_id)
        assert result['exitCode'] == code, result
        await until(pilot, lambda: view.query_one_optional(f'#{terminal_id}', TerminalTool) is not None)
        widget = view.query_one(f'#{terminal_id}', TerminalTool)
        await until(pilot, lambda: widget.is_finalized)
        assert widget.execution is execution and widget.state is execution.state
        assert widget.has_class('-success' if code == 0 else '-error')
        if code:
            assert '[7]' in str(widget.border_title)
        view.window.scroll_end(animate=False, immediate=True)
        await until(pilot, lambda: text in frame())
        completions.append({'terminal': terminal_id, 'exit_code': code, 'painted': text})
    terminal_id = (await rpc('terminal/create', command='sh',
        args=['-c', "printf 'NATIVE_RUNNING\\n'; sleep 30"]))['terminalId']
    execution = agent.controller.terminals.require(terminal_id)
    await until(pilot, lambda: view.query_one_optional(f'#{terminal_id}', TerminalTool) is not None)
    widget = view.query_one(f'#{terminal_id}', TerminalTool)
    assert not widget.is_finalized and not execution.outcome.finished
    await rpc('terminal/kill', terminalId=terminal_id)
    killed = await rpc('terminal/wait_for_exit', terminalId=terminal_id)
    assert killed['signal'] == signal.Signals(signal.SIGKILL).name
    await until(pilot, lambda: widget.is_finalized)
    assert widget.has_class('-error') and 'SIGKILL' in str(widget.border_title)
    view.window.scroll_end(animate=False, immediate=True)
    await until(pilot, lambda: 'NATIVE_RUNNING' in frame())
    app.save_screenshot('terminal-outcomes.svg', path=str(evidence))
    for identifier in tuple(agent.controller.terminals.executions):
        await rpc('terminal/release', terminalId=identifier)
    assert pty_masters() == initial_masters
    assert agent.process.process is process and process.returncode is None
    assert not requests
    evidence.joinpath('native-views-receipt.json').write_text(json.dumps({
        'result': 'PASS', 'elapsed_seconds': time.monotonic() - started,
        'original_permission_future_after_detach_reattach': True,
        'native_pilot_diff_allow_retained_diff_reject_inline_allow': True,
        'real_pty_terminal_completion': completions,
        'real_pty_signal_completion': killed,
        'same_terminal_execution_and_state': True, 'original_agent_process_retained': True,
        'pty_masters_before': sorted(initial_masters), 'pty_masters_after': sorted(pty_masters()),
        'provider_requests': len(requests),
        'scope': 'Actual installed Toad/ACP/Pi/PTY; native Textual Pilot/compositor, not a physical st capture. No prompt/provider/public input. Startup-failed terminal native drawing is source-reviewed, not claimed as rendered.'
    }, indent=2) + '\n')


if __name__ == '__main__':
    asyncio.run(main(app_type=InstalledApp, acceptance=acceptance,
                    fixture_stage=os.environ['U356_FIXTURE_ROOT'], provider_request_budget=0))
