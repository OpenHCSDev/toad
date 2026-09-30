"""Continuous actual installed native/ACP message, delayed chunks and headers."""
import asyncio
from importlib.metadata import distribution
import json
import os
from pathlib import Path
import time

from agent_comms.transcript_events import AgentTextTranscript, UserTranscript
from l0a_native_installed_pilot import main, until, response_painted
from runtime_fixture import ToadApp
from toad.widgets.agent_response import AgentResponse
from toad.widgets.message_divider import MessageDivider


TEXT = ('An original answer retains its message identity across each provider chunk. '
        'A sentence must not acquire a new header merely because the provider pauses.\n\n') * 6 + 'STREAM_HEADER_END_PROOF'
chunks = []


def reply(request, number):
    assert number == 1
    return {'role': 'assistant', 'content': TEXT}, 'stop'


def after_chunk(number, index):
    chunks.append({'request': number, 'index': index, 'at': time.monotonic()})
    time.sleep(.12)


def observe(app, view):
    viewport = view.window.region
    return [{'resource': id(body), 'text': body.source,
             'region': str(body.region),
             'painted': body in app.screen._compositor.visible_widgets and body.region.overlaps(viewport),
             'header_count': sum(divider.label == 'Agent' for divider in body.query(MessageDivider)),
             'history_resources': [id(parent) for parent in body.ancestors
                                   if type(parent).__name__ == 'TranscriptHistory']}
            for body in view.contents.query(AgentResponse)]


async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    evidence = Path(os.environ['L0A_EVIDENCE'])
    view = app.selected_session.conversation
    release.set()
    hold_next.clear()
    await until(pilot, lambda: view.agent_ready)
    token = os.environ['STREAM_INPUT_TOKEN']
    view.prompt.text = token
    view.prompt.prompt_text_area.focus()
    await pilot.press('enter')
    observations = []
    began = time.monotonic()
    try:
        async with asyncio.timeout(35):
            while not response_painted(app, view, 'STREAM_HEADER_END_PROOF'):
                observations.append({'elapsed': time.monotonic()-began, 'bodies': observe(app, view)})
                await pilot.pause(.1)
    finally:
        (evidence/'stream-observations.json').write_text(json.dumps(observations, indent=2)+'\n')
        app.save_screenshot(str(evidence/'last-stream-frame.svg'))
    await until(pilot, lambda: not comms.registry.require('beta').executing)
    await pilot.pause()
    observations.append({'elapsed': time.monotonic()-began, 'bodies': observe(app, view)})
    page = comms.transcripts.thread_transcript_page('beta')
    users = [event for event in page.events if isinstance(event, UserTranscript)
             and event.text == token]
    responses = [event for event in page.events if isinstance(event, AgentTextTranscript)]
    receipt = {'pins': {name: json.loads(distribution(name).read_text('direct_url.json'))
                       for name in ('batrachian-toad','agent-comms','textual')},
               'observations': observations, 'provider_chunks': chunks,
               'provider_requests': len(requests), 'native_users': len(users),
               'canonical_answer_events': len(responses),
               'canonical_answer_text': ''.join(event.text for event in responses),
               'input_replays': 0}
    (evidence/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    app.save_screenshot(str(evidence/'settled-stream.svg'))
    assert len(requests) == 1 and len(users) == 1
    assert receipt['canonical_answer_text'] == TEXT
    assert all(sum(body['header_count'] for body in row['bodies']) <= 1 for row in observations)
    assert app._exception is None


if __name__ == '__main__':
    asyncio.run(main(app_type=ToadApp, acceptance=acceptance, provider_reply=reply,
                     provider_request_budget=1, provider_chunk_characters=25,
                     provider_after_chunk=after_chunk,
                     fixture_stage=Path(os.environ['STREAM_FIXTURE_STAGE'])))
