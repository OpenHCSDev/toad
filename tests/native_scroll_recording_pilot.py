"""Seed real saved Pi history, then record the installed UI's scroll journey.

Reuses the existing native loopback fixture and isolated st/Xvfb recorder. No
UI, transport, renderer or source is substituted. Capture is not assessment.
"""
import asyncio
import json
import os
from pathlib import Path
import shlex
import sys
import subprocess

from l0a_native_installed_pilot import main, until
from native_session_retention_pilot import InstalledApp, conversation_paint
from tools.record_installed_tui import ProcessOwner


def reply(request, number):
    if number > 1:
        return {'role': 'assistant', 'content': 'NATIVE RECORDING OWNER SURVIVED'}, 'stop'
    sections = '\n\n'.join(
        f'### Saved block {index}\n\n| key | value |\n| --- | --- |\n'
        f'| {index} | owned source |\n\n```python\nsample_{index} = "SOURCE-{index}"\n```'
        for index in range(32)
    )
    return {'role': 'assistant', 'content': f'# NATIVE SAVED RESPONSE {number}\n\n{sections}\n\nNATIVE SOURCE END'}, 'stop'


async def record(app, pilot, agent, comms, entered, release, hold_next, requests):
    release.set()
    view = app.selected_session.conversation
    await until(pilot, lambda: view.turns.owner.accepts_prompt and view.submissions.queue_projection.status == 'available')
    editor = view.prompt.prompt_text_area
    assert await pilot.click(editor)
    editor.insert('Produce the controlled rich saved scroll source.')
    await pilot.press('enter')
    await until(pilot, lambda: len(requests) == 1 and not comms.registry.require('beta').executing)
    view.transcript.require_checkpoint()
    await until(pilot, lambda: 'NATIVE SOURCE END' in conversation_paint(app.screen))
    source = await agent.get_transcript_page()
    evidence = Path(os.environ['L0A_EVIDENCE'])
    evidence.mkdir(parents=True, exist_ok=True)
    session_file = Path(source.after.session_file)
    assert 'NATIVE SOURCE END' in session_file.read_text()
    (evidence / 'saved-native-journal.jsonl').write_bytes(session_file.read_bytes())
    (evidence / 'seed.json').write_text(json.dumps({
        'native_requests': len(requests), 'cursor': repr(source.after),
        'response_characters': len(reply({}, 1)[0]['content']),
        'native_owner': repr(comms.registry.require('beta').process_identity),
    }, indent=2))
    recorder = Path(__file__).parent / 'tools/record_installed_tui.py'
    actions = evidence / 'scroll.xdo'
    custody = ProcessOwner(comms.registry)
    await asyncio.to_thread(custody.run,
        [sys.executable, str(recorder), '--write-journey-script', str(actions)],
        os.environ.copy(), timeout=10, stdout=subprocess.PIPE)
    runtime = Path(sys.prefix) / 'bin'
    env = dict(os.environ, AGENT_COMMS_RUNTIME_ROOT=str(runtime))
    output = evidence / ('profiled' if os.environ.get('SCROLL_PROFILE') == '1' else 'unprofiled')
    command = [sys.executable, str(recorder), '--private-root', str(comms.root),
               '--owner', 'toad-viewport-demand-214', '--actions', str(actions), '--fit-window',
               '--startup-wait', '12', '--max-duration', '50', '--review-seconds', '5',
               '--review-frames', '40', '--review-timing', 'deferred', '--output', str(output)]
    for phase in ('up', 'down', 'reverse', 'end', 'idle'):
        command.extend(('--review-phase', phase))
    if os.environ.get('SCROLL_PROFILE') == '1':
        command.append('--profile')
        if threads := os.environ.get('SCROLL_PROFILE_THREADS'):
            command.extend(('--profile-threads', threads))
    command.extend(('--', str(runtime / 'toad'), 'acp',
                    shlex.join((str(runtime / 'python'), '-m', 'agent_comms.acp')),
                    str(agent.project_root_path), '--session', 'beta'))
    try:
        with (evidence / 'recorder-controller.log').open('wb') as log:
            await asyncio.to_thread(custody.run, command, env,
                                    timeout=100, stdout=log, stderr=subprocess.STDOUT)
    finally:
        cleanup = await asyncio.to_thread(custody.cleanup)
        (evidence / 'controller-cleanup.json').write_text(json.dumps(cleanup, indent=2))
        assert not cleanup['remaining_owned_pids'] and not cleanup['errors'], cleanup
    assert len(requests) == 1, 'Navigation must never send a model prompt'
    assert comms.registry.require('beta').process_alive
    # Recording must leave the same real owner usable by its original surface.
    assert await pilot.click(editor)
    editor.insert('Confirm the original recording owner still answers.')
    await pilot.press('enter')
    await until(pilot, lambda: 'NATIVE RECORDING OWNER SURVIVED' in conversation_paint(app.screen))
    assert len(requests) == 2


if __name__ == '__main__':
    asyncio.run(main(app_type=InstalledApp, acceptance=record, provider_reply=reply,
                     provider_request_budget=2))
