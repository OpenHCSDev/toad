"""Physical native reply -> actual client RPC file/terminal/permission -> retained paint."""
import asyncio
import os
from pathlib import Path
from importlib.resources import files
from l0a_native_installed_pilot import main, until, response_painted
from runtime_fixture import ToadApp
from toad.screens.permissions import PermissionReview
from toad.widgets.terminal_tool import TerminalTool
from toad.navigation_target import channel_target

class InstalledApp(ToadApp):
    CSS_PATH = files('toad').joinpath('toad.tcss')

async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    view = app.selected_session.conversation
    mode = app.selected_mode
    release.set(); hold_next.clear()
    await until(pilot, lambda: view.agent_ready)
    view.prompt.text = 'CLIENT_SESSION_SAVED_HISTORY'
    view.prompt.prompt_text_area.focus()
    await pilot.press('enter')
    await until(pilot, lambda: response_painted(app, view, 'NATIVE_RESPONSE_1'))
    await until(pilot, lambda: not comms.registry.require('beta').executing)
    call_id = 100
    async def rpc(method, **params):
        nonlocal call_id
        call_id += 1
        result = await agent.server.call({'jsonrpc': '2.0', 'id': call_id,
            'method': method, 'params': {'sessionId': agent.session_id, **params}})
        assert 'error' not in result, result
        return result['result']
    await rpc('fs/write_text_file', path='client.txt', content='old client value\nretained line')
    assert (await rpc('fs/read_text_file', path='client.txt', line=2, limit=1))['content'] == 'retained line'
    tool = {'toolCallId': 'client-edit', 'title': 'CLIENT_BOUND_PERMISSION', 'kind': 'edit',
        'content': [{'type': 'diff', 'path': str(agent.project_root_path/'client.txt'),
                    'oldText': 'old client value', 'newText': 'CLIENT_NEW_VALUE'}]}
    agent.updates.accept(agent.session_id, {'sessionUpdate': 'tool_call', **tool, 'status': 'in_progress'})
    permission = asyncio.create_task(rpc('session/request_permission',
        options=[{'optionId': 'allow', 'name': 'Allow once', 'kind': 'allow_once'},
                 {'optionId': 'reject', 'name': 'Reject', 'kind': 'reject_once'}],
        toolCall={'toolCallId': 'client-edit'}))
    await until(pilot, lambda: isinstance(app.screen, PermissionReview))
    await until(pilot, lambda: 'CLIENT_NEW_VALUE' in '\n'.join(
        strip.text for strip in app.screen._compositor.render_strips()))
    frame = '\n'.join(strip.text for strip in app.screen._compositor.render_strips())
    assert 'CLIENT_NEW_VALUE' in frame and 'Allow' in frame, frame
    await pilot.press('a')
    assert (await permission)['outcome'] == {'outcome': 'selected', 'optionId': 'allow'}
    await rpc('fs/write_text_file', path='client.txt', content='CLIENT_NEW_VALUE\nretained line')
    assert (agent.project_root_path/'client.txt').read_text().startswith('CLIENT_NEW_VALUE')
    terminal_id = (await rpc('terminal/create', command='sh',
        args=['-c', "printf 'CLIENT_TERMINAL_RETAINED\\n'"]))['terminalId']
    assert (await rpc('terminal/wait_for_exit', terminalId=terminal_id))['exitCode'] == 0
    assert 'CLIENT_TERMINAL_RETAINED' in (await rpc('terminal/output', terminalId=terminal_id))['output']
    await until(pilot, lambda: 'CLIENT_TERMINAL_RETAINED' in '\n'.join(
        strip.text for strip in app.screen._compositor.render_strips()))
    execution = agent.controller.terminals.require(terminal_id)
    view.prompt.text = 'CLIENT_SESSION_UNSENT_DRAFT'
    document = view.prompt.prompt_text_area.document
    undo = view.prompt.prompt_text_area.history
    await app.open_comms_session(owner_mode=mode, project_path=agent.project_root_path,
        me=comms.messaging.user_identity(str(agent.project_root_path)).name, target=channel_target('#team'))
    await app.select_session(mode)
    returned = app.selected_session.conversation
    assert returned.agent is agent and agent.controller.terminals.require(terminal_id) is execution
    await until(pilot, lambda: returned.query_one_optional(f'#{terminal_id}', TerminalTool) is not None)
    await until(pilot, lambda: 'CLIENT_TERMINAL_RETAINED' in '\n'.join(
        strip.text for strip in app.screen._compositor.render_strips()))
    assert returned.prompt.text == 'CLIENT_SESSION_UNSENT_DRAFT'
    assert returned.prompt.prompt_text_area.document is document
    assert returned.prompt.prompt_text_area.history is undo
    await rpc('terminal/release', terminalId=terminal_id)
    # Keep actual request futures across optional projection detach/reattach.
    pending = asyncio.create_task(rpc('session/request_permission',
        options=[{'optionId': 'allow', 'name': 'Allow once', 'kind': 'allow_once'},
                 {'optionId': 'reject', 'name': 'Reject', 'kind': 'reject_once'}],
        toolCall={**tool, 'toolCallId': 'retained-permission'}))
    try:
        await until(pilot, lambda: isinstance(app.screen, PermissionReview), 5)
    except TimeoutError:
        print('RETURN_PERMISSION_DIAGNOSTIC', {'surface_is_returned': agent.controller.surface.target is returned,
            'ready': agent.ready, 'view_ready': returned.agent_ready, 'view_mounted': returned.is_mounted,
            'view_closing': returned._closing, 'process_accepts': agent.process.accepts_session(agent.session_id),
            'requests': len(agent.permissions.pending), 'task_done': pending.done(),
            'result': pending.result() if pending.done() else None, 'screen': repr(app.screen),
            'view_screen': repr(returned.screen), 'mode': app.current_mode}, flush=True)
        Path(os.environ['L0A_EVIDENCE'], 'return-permission-red.svg').write_text(app.export_screenshot())
        raise
    owned_request, = agent.permissions.pending
    agent.detach_surface(returned)
    await until(pilot, lambda: not isinstance(app.screen, PermissionReview))
    assert owned_request.pending and not agent.controller.surface.owns(returned)
    agent.attach_surface(returned)
    await until(pilot, lambda: isinstance(app.screen, PermissionReview))
    await until(pilot, lambda: 'CLIENT_NEW_VALUE' in '\n'.join(
        strip.text for strip in app.screen._compositor.render_strips()))
    assert agent.permissions.pending == (owned_request,)
    await pilot.press('r')
    assert (await pending)['outcome'] == {'outcome': 'selected', 'optionId': 'reject'}
    replacing = asyncio.create_task(rpc('session/request_permission',
        options=[{'optionId': 'allow', 'name': 'Allow once', 'kind': 'allow_once'}],
        toolCall={**tool, 'toolCallId': 'replaced-permission'}))
    await until(pilot, lambda: isinstance(app.screen, PermissionReview))
    original_session = agent.session_id
    await agent.acp_new_session()
    assert agent.session_id != original_session
    assert (await replacing)['outcome'] == {'outcome': 'cancelled'}
    stopped = asyncio.create_task(rpc('session/request_permission',
        options=[{'optionId': 'allow', 'name': 'Allow once', 'kind': 'allow_once'}],
        toolCall={**tool, 'toolCallId': 'stopped-permission'}))
    await until(pilot, lambda: isinstance(app.screen, PermissionReview))
    await agent.stop()
    assert (await stopped)['outcome'] == {'outcome': 'cancelled'}
    assert not agent.permissions.pending and not agent.controller.terminals.executions
    assert len(requests) == 1
    Path(os.environ['L0A_EVIDENCE'], 'client-session.svg').write_text(app.export_screenshot())
    print('PASS actual native reply/physical grant+retained reject/session replacement+stop/shared tool merge/files/terminal/source return/draft undo; one loopback request', flush=True)

if __name__ == '__main__':
    asyncio.run(main(app_type=InstalledApp, acceptance=acceptance))
