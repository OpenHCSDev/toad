"""Changed feedback through the existing installed App/ACP/Pi fixture."""
import asyncio
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests'))
sys.path.insert(0, str(ROOT / 'evidence/headless-agent-services-u2-20261003'))
from installed_services import InstalledApp
from l0a_native_installed_pilot import main, until
from agent_comms.field_codec import FieldCodec
from toad.core.events import CoreEvent, LogAgentFail, UnsupportedResumeAgentFail
from toad.acp.status import StopReason
from toad.widgets.tool_call import ToolCall
from toad.widgets.agent_response import AgentResponse
from toad.widgets.markdown_note import MarkdownNote
from toad.acp.client_session import ClientSessionRequest


async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    started = time.monotonic()
    evidence = Path(os.environ['L0A_EVIDENCE'])
    view = app.selected_session.conversation
    surface = agent.controller.surface
    await until(pilot, lambda: view.agent_ready)
    # The original snapshot claim can retire an idle projection. Observe its
    # real native mount, not indefinite DOM retention. This instrumentation
    # calls the original mount/body handler unchanged and records only output;
    # no backend turn, source coverage, widget state or provider input is forged.
    headers = {}
    mounted = []
    original_mount = ToolCall.on_mount
    async def record_mount(widget):
        await original_mount(widget)
        call = widget.tool_call.call
        headers[call.status] = widget.query_one('ToolCallHeader').content.plain
        mounted.append({'id': call.tool_call_id, 'attached': widget.is_attached,
                        'status': call.status, 'header': headers[call.status]})
        (evidence / 'native-mount-observations.json').write_text(json.dumps(mounted, indent=2)+'\n')
    ToolCall.on_mount = record_mount
    # Real SDK notification admission, process worker validation, original
    # CoreEvent publication, native MessagePump and mounted ToolCall header.
    for status in ('pending', 'in_progress', 'completed', 'failed'):
        tool_id = f'feedback-{status}'
        authority = ClientSessionRequest(agent, agent.session_id)
        authority.require()
        result = await agent.server.call({
            'jsonrpc': '2.0', 'id': 400 + len(headers), 'method': 'session/update',
            'params': {'sessionId': agent.session_id, 'update': {
                'sessionUpdate': 'tool_call', 'toolCallId': tool_id,
                'title': f'FEEDBACK_{status.upper()}', 'status': status, 'kind': 'other',
            }},
        })
        (evidence / f'admission-{status}.json').write_text(json.dumps({
            'registered_client_result': result,
            'authority_current': authority.current,
            'original_tool_keys': list(agent.tools.calls),
            'original_subscription_active': surface.subscription.active,
            'original_surface_target_is_view': surface.owns(view),
        }, indent=2) + '\n')
        assert result is not None and 'error' not in result, result
        assert tool_id in agent.tools.calls, 'Original SDK notification was not admitted'
        try:
            await until(pilot, lambda: status in headers, 5)
        except BaseException:
            (evidence / 'projection-diagnostic.json').write_text(json.dumps({
                'contents_attached': view.contents.is_attached,
                'view_attached': view.is_attached,
                'turn_busy': view.turns.owner.busy,
                'handlers': [handler.__qualname__ for handler in
                             view.handlers_for(__import__('toad.core.events',fromlist=['ToolCall']).ToolCall(
                                 __import__('toad.acp.status',fromlist=['ToolCallStatus']).ToolCallStatus.from_acp(agent.tools.calls[tool_id])))],
                'mounted': mounted,
                'children': [repr(child) for child in view.contents.children],
                'app_exception': repr(app._exception),
            },indent=2)+'\n')
            raise
        assert f'FEEDBACK_{status.upper()}' in headers[status]
    assert '⌛' in headers['pending'] and 'running' in headers['in_progress']
    assert '✔' in headers['completed'] and 'failed' in headers['failed']
    ToolCall.on_mount = original_mount
    assert not comms.registry.require('beta').executing
    # Native turn-completion callback is the changed reason consumer. No
    # prompt/provider call is made; actual backend stop generation is not claimed.
    before = len(view.query('.-stop-reason'))
    for reason in StopReason.members_with(StopReason):
        await view.agent_turn_over(reason)
    await pilot.pause()
    notes = tuple(view.query('.-stop-reason'))
    assert len(notes) - before == 3
    assert all(isinstance(note, MarkdownNote) for note in notes)
    texts = tuple(note.source for note in notes)
    assert all('$AGENT' not in text for text in texts)
    assert any('maximum output tokens' in text for text in texts)
    assert any('maximum number of model requests' in text for text in texts)
    assert any('refused to continue' in text for text in texts)
    # Original typed failures cross their existing stream and native pump.
    path = evidence / 'original log #%.txt'
    path.write_text('Private synthetic diagnostic, no credentials.\n')
    log = LogAgentFail('FEEDBACK_LOG_FAILURE', 'original details', log_path=path)
    help_event = UnsupportedResumeAgentFail('FEEDBACK_RESUME_FAILURE')
    for event in (log, help_event):
        encoded = FieldCodec.encode(event)
        assert FieldCodec.decode(CoreEvent, encoded) == event
        agent.events.publish(event)
    await until(pilot, lambda: any(
        'Agent does not support resume' in note.source for note in view.query(MarkdownNote)))
    links = tuple(view.query('.-error-log-link'))
    assert len(links) == 1 and isinstance(links[0], AgentResponse)
    assert 'original%20log%20%23%25.txt' in links[0].source
    # Native Markdown already disables automatic browser opening at its
    # constructor boundary. No link click/browser/authentication occurs here.
    from toad.conversation_markdown import ConversationMarkdown
    assert all(not markdown._open_links for markdown in view.query(ConversationMarkdown))
    assert surface is agent.controller.surface and surface.owns(view)
    assert agent.session.connected and len(requests) == 0
    assert app._exception is None
    (evidence / 'feedback.svg').write_text(app.export_screenshot())
    (evidence / 'feedback-receipt.json').write_text(json.dumps({
        'result': 'PASS', 'elapsed_seconds': time.monotonic() - started,
        'actual_installed_source': {
            'toad': str(Path(sys.modules['toad'].__file__).resolve()),
            'agent_comms': str(Path(sys.modules['agent_comms'].__file__).resolve()),
        },
        'sdk_notifications_native_headers': headers,
        'actual_native_mount_observations': mounted,
        'all_declared_stop_reason_callbacks': StopReason.names(),
        'stop_notes': texts,
        'typed_failure_codec_and_native_stream': True,
        'original_log_path_encoded_once_by_native_presentation': str(path),
        'failure_help_and_single_log_link': True,
        'same_original_surface_and_connected_acp': True,
        'browser_autoload_disabled': True,
        'provider_requests': len(requests),
        'scope': 'Actual installed Toad/ACP/Pi and native Pilot. No prompt or provider request. Official SDK fixture tool notifications use the original registered validator/publication and actual native mount; settled projection retention or real native tool execution is not claimed. Non-default stop reasons exercise the native completion callback without backend generation of those reasons. Failures use original typed stream without causing a real backend outage. No physical pixel, paid provider, complete headless or public/default readiness claim.'
    }, indent=2) + '\n')


if __name__ == '__main__':
    asyncio.run(main(app_type=InstalledApp, acceptance=acceptance,
                    fixture_stage=os.environ['U359_FIXTURE_ROOT'], provider_request_budget=0))
