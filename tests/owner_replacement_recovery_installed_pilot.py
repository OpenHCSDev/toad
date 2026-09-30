"""Real failed ACP load, replaced native owner, same open view recovery.

The old installed owner is an actual producer of the missing receipt-frontier
schema, not a mocked ACP response. Only a disposable private bus and loopback
provider are used. Baseline and candidate use the same continuous application.
"""

import asyncio
import json
import os
from pathlib import Path
import shlex
import time

from acp.schema import TextContentBlock
from agent_comms.acp import CommsClient
from agent_comms.field_codec import FieldCodec
from l0a_native_installed_pilot import main, response_painted, until
from restored_inbound_continuous_installed_pilot import SeedSubscriber
from runtime_fixture import ToadApp, wait_channel_roster
from toad import jsonrpc
from toad.acp import api
from toad.widgets.transcript_history import TranscriptHistory
from toad.widgets.comms_sidebar import CommsRow


class HealthyWindow(ToadApp):
    def __init__(self, *args, **kwargs):
        kwargs['agent_session_id'] = 'alpha'
        super().__init__(*args, **kwargs)


async def prepare(comms, project, requests, entered, release, hold_next):
    package = Path(os.environ['AGENT_COMMS_PRIVATE_NK_NATIVE_PACKAGE'])
    root_id = os.environ['AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID']
    comms.owners.pin_private_nk_launch(comms.root, root_id, package)
    hold_next.clear()
    release.set()
    peer = CommsClient(comms, runtime_enabled=True,
                       private_nk_native_package=package,
                       private_nk_wire_root_id=root_id)
    peer.on_connect(SeedSubscriber())
    try:
        await peer.load_session(cwd=str(project), session_id='beta')
        await peer.prompt('beta', [TextContentBlock(type='text', text='SAVED_RECOVERY_SOURCE')])
    finally:
        await peer.shutdown()
    assert len(requests) == 1
    await asyncio.to_thread(comms.owners.stop, 'beta')
    if os.environ.get('ATTACHMENT_HEALTHY_WINDOW'):
        from agent_comms.thread_management import ForkSpec
        await asyncio.to_thread(comms.threads.fork, ForkSpec('alpha', 'beta', prompt=''))
    # Real installed old producer; its launch receives the same explicit typed
    # private route pins. No live user owner is involved.
    old_python = os.environ['ATTACHMENT_OLD_RUNTIME'] + '/bin/python'
    script = '''
import os,shlex
from pathlib import Path
from agent_comms.comms import Comms
c=Comms(Path(os.environ['AGENT_COMMS_ROOT']))
c.owners.pin_private_nk_launch(c.root, os.environ['AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID'],
                             Path(os.environ['AGENT_COMMS_PRIVATE_NK_NATIVE_PACKAGE']))
r=c.owners.start('beta', agent_bin='pi', agent_args=shlex.split(os.environ['AGENT_COMMS_AGENT_ARGS']))
print(r.pid)
'''
    old_env = dict(os.environ,
        AGENT_COMMS_PRIVATE_NK_NATIVE_PACKAGE=os.environ['ATTACHMENT_OLD_NATIVE_PACKAGE'])
    process = await asyncio.create_subprocess_exec(old_python, '-c', script, env=old_env,
                  stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    output, error = await process.communicate()
    assert process.returncode == 0, error.decode()
    assert int(output) == comms.registry.require('beta').pid
    print('REAL_OLD_OWNER_STARTED', flush=True)


async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    evidence = Path(os.environ['L0A_EVIDENCE'])
    view = app.selected_session.conversation
    if os.environ.get('ATTACHMENT_HEALTHY_WINDOW'):
        sidebar = await wait_channel_roster(app, pilot, '#team')
        row = next(row for row in sidebar.query(CommsRow) if row.target_name == 'beta')
        row.scroll_visible(animate=False, immediate=True)
        await pilot.pause()
        assert await pilot.click(row), 'Actual beta channel-row click was not delivered'
        await until(pilot, lambda: app.selected_session.conversation.agent is not None
                    and app.selected_session.conversation.agent.session_id == 'beta')
        view = app.selected_session.conversation
        agent = view.agent
        await until(pilot, agent.session.settled.is_set)
    assert not agent.session.connected and agent.session.settled.is_set()
    assert agent.coordination is not None
    initial_pid = comms.registry.require('beta').pid
    initial_log = agent.presentation.log_path.read_text()
    assert 'receipt_frontier' in initial_log, initial_log[-3000:]
    (evidence / 'initial-failed-attachment.txt').write_text(initial_log)
    editor = view.prompt.prompt_text_area
    editor.focus()
    await pilot.press('d', 'r', 'a', 'f', 't')
    before = editor.capture_editor_state()
    assert editor.text == 'draft', (editor.text, editor.disabled)
    original_history = tuple(view.contents.query(TranscriptHistory))
    requests_before = len(requests)
    clock = time.monotonic()
    await asyncio.to_thread(comms.owners.stop, 'beta')
    replacement = await asyncio.to_thread(comms.owners.start, 'beta')
    assert replacement.pid != initial_pid
    # No reconnect() call, source request, tab reopening or synthetic activity
    # is made here. The mounted observer sees the actual registry replacement.
    try:
        await until(pilot, lambda: agent.session.connected and view.agent_ready, 20)
    except TimeoutError:
        (evidence / 'unrecovered-open-view.json').write_text(json.dumps({
            'old_pid': initial_pid, 'replacement_pid': replacement.pid,
            'same_view': app.selected_session.conversation is view,
            'connected': agent.session.connected,
            'requests': len(requests),
        }, indent=2))
        raise AssertionError('Actual continuously OPEN failed view did not recover on owner replacement')
    recovered_seconds = time.monotonic() - clock
    assert app.selected_session.conversation is view and view.agent is agent
    assert view.prompt.prompt_text_area is editor
    after = editor.capture_editor_state()
    assert after.document is before.document and after.history is before.history
    assert editor.text == 'draft'
    assert len(requests) == requests_before, 'Read-only recovery called the provider'
    assert comms.registry.require('beta').pid == replacement.pid
    await until(pilot, lambda: bool(view.contents.query(TranscriptHistory)))
    assert all(history.is_attached for history in original_history)
    await pilot.press('ctrl+z')
    assert editor.text != 'draft', 'Actual original undo stack was lost'
    # One new explicit fixture input proves the recovered original view works.
    view.prompt.text = 'FIRST_INPUT_AFTER_RECOVERY'
    editor.focus()
    await pilot.press('enter')
    await until(pilot, lambda: len(requests) == 2 and not comms.registry.require('beta').executing)
    await until(pilot, lambda: response_painted(app, view, 'NATIVE_RESPONSE_2'))
    assert len(requests) == 2
    from agent_comms.session_load import ExistingSessionLoadAdmission
    from agent_comms.thread_presentation import LiveThreadOwnerBinding
    snapshot = comms.registry.snapshot()
    expected = LiveThreadOwnerBinding(snapshot.owner_identity('beta'),
                                     snapshot.require_active('beta').require_process())
    # The strict command crosses the actual installed ACP router. A stopped
    # expected owner must be refused without silently launching a replacement.
    await asyncio.to_thread(comms.owners.stop, 'beta')
    with agent.request():
        result = api.session_load(str(agent.project_root_path), [], agent.session_id,
                                  ExistingSessionLoadAdmission(expected).metadata())
    try:
        await result.wait()
    except jsonrpc.APIError as error:
        refusal = str(error)
    else:
        raise AssertionError('Read-only reattachment started or accepted a stopped owner')
    assert not comms.registry.require('beta').process_alive
    assert len(requests) == 2
    (evidence / 'receipt.json').write_text(json.dumps({
        'same_open_view_recovered': True, 'recovery_seconds': recovered_seconds,
        'healthy_window_physical_beta_click': bool(os.environ.get('ATTACHMENT_HEALTHY_WINDOW')),
        'same_agent_editor_document_undo': True,
        'existing_history_retained': len(original_history),
        'requests_during_recovery': len(requests) - 2,
        'explicit_new_input_replied': True,
        'strict_stopped_owner_load_refused': refusal,
        'original_inputs_retried': 0,
        'binding': FieldCodec.encode(expected),
    }, indent=2))
    # Stop this fixture's ACP adapter before App teardown; normal UI closure
    # intentionally retains native owners, whereas this runner owns the adapter.
    await agent.stop()
    print('SAME_OPEN_OWNER_REPLACEMENT_RECOVERY_PASS', recovered_seconds, flush=True)


if __name__ == '__main__':
    healthy = bool(os.environ.get('ATTACHMENT_HEALTHY_WINDOW'))
    asyncio.run(main(prepare_state=prepare, acceptance=acceptance,
                     app_type=HealthyWindow if healthy else ToadApp,
                     attachment_expected=healthy, provider_request_budget=2))
