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
from toad.widgets.coordination_context import CoordinationContext
from toad.live_output import ResponseStream


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

    def sample():
        stream = view.output.streams.get(ResponseStream)
        return {'elapsed': time.monotonic()-began, 'bodies': observe(app, view),
                'active_response_resource': id(stream.block) if stream is not None and stream.block is not None else None,
                'context_resources': [id(body) for body in view.contents.query(CoordinationContext)],
                'source_covers_answer': any(isinstance(event, AgentTextTranscript)
                                           for history in view.window.histories
                                           for event in history.coverage_events)}

    try:
        async with asyncio.timeout(35):
            while not response_painted(app, view, 'STREAM_HEADER_END_PROOF'):
                observations.append(sample())
                await pilot.pause(.1)
    finally:
        (evidence/'stream-observations.json').write_text(json.dumps(observations, indent=2)+'\n')
        app.save_screenshot(str(evidence/'last-stream-frame.svg'))
    await until(pilot, lambda: not comms.registry.require('beta').executing)
    await pilot.pause()
    observations.append(sample())
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
    assert any(row['context_resources'] for row in observations)
    # Original source context does not cover the assistant still being streamed.
    # That publication may not replace its existing native resource association.
    uncovered = {row['active_response_resource'] for row in observations
                 if row['active_response_resource'] is not None and not row['source_covers_answer']}
    assert len(uncovered) == 1, uncovered
    assert app._exception is None


async def interaction_acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    """Measure original sidebar frames and input while native ACP chunks arrive."""
    from toad.widgets.side_bar import SideBar, SidebarSlider
    import cProfile

    evidence = Path(os.environ['L0A_EVIDENCE'])
    view = app.selected_session.conversation
    release.set()
    hold_next.clear()
    await until(pilot, lambda: view.agent_ready)
    if os.environ.get('STREAM_RESIZE_PROFILE') == '1':
        # Panel hydration is independent of the first visible sidebar frame.
        # Admit the original controls before starting the measured turn.
        for selector in ('#channels-sidebar', '#thread-sidebar'):
            bar = next(bar for bar in app.screen.query(selector) if bar.presentation_visible)
            collapsed = bar.collapsed
            if collapsed:
                bar.reveal()
            await asyncio.wait_for(bar.wait_content_ready(), 10)
            if collapsed:
                bar.toggle(focus=False)
        await pilot.pause()
    token = os.environ['STREAM_INPUT_TOKEN']
    view.prompt.text = token
    view.prompt.prompt_text_area.focus()
    await pilot.press('enter')
    await until(pilot, lambda: ResponseStream in view.output.streams)
    rows = []
    try:
        for selector in ('#channels-sidebar', '#thread-sidebar'):
            bar = next(bar for bar in app.screen.query(selector) if bar.presentation_visible)
            for _ in range(2):
                assert comms.registry.require('beta').executing
                chunk_before = len(chunks)
                original = bar.collapsed
                painted = app.next_frame = asyncio.get_running_loop().create_future()
                started = time.perf_counter()
                bar.toggle(focus=False)
                shown = await asyncio.wait_for(painted, 5)
                rows.append({'sidebar': selector, 'collapsed': bar.collapsed,
                             'frame_ms': (shown-started)*1000,
                             'native_turn_busy_before': True,
                             'chunks_before': chunk_before, 'chunks_after': len(chunks)})
                assert bar.collapsed != original
                app.next_frame = None
            if os.environ.get('STREAM_RESIZE_PROFILE') == '1':
                if bar.collapsed:
                    painted = app.next_frame = asyncio.get_running_loop().create_future()
                    bar.toggle(focus=False)
                    await asyncio.wait_for(painted, 5)
                    app.next_frame = None
                slider = bar.query_one('#sidebar-width-slider', SidebarSlider)
                for direction in (-1, 1):
                    assert comms.registry.require('beta').executing
                    painted = app.next_frame = asyncio.get_running_loop().create_future()
                    profile = app.frame_profiler = cProfile.Profile()
                    before = app.sidebar_layout.get(bar.id).width_percent
                    started = time.perf_counter()
                    profile.enable()
                    slider.action_step(direction)
                    shown = await asyncio.wait_for(painted, 5)
                    profile.disable()
                    profile.dump_stats(str(evidence / f'{bar.id}-resize-{direction}.pstats'))
                    rows.append({'sidebar': selector, 'action': 'resize',
                                 'slider_direction': direction,
                                 'width_before': before,
                                 'width_after': app.sidebar_layout.get(bar.id).width_percent,
                                 'frame_ms': (shown-started)*1000,
                                 'native_turn_busy_before': True})
                    # The slider owns direction reversal on a right edge;
                    # this observer records its answer rather than mirroring it.
                    assert app.sidebar_layout.get(bar.id).width_percent != before
                    app.frame_profiler = None
                    app.next_frame = None
        view.prompt.prompt_text_area.focus()
        started = time.perf_counter()
        # Pilot.press intentionally waits for global idle after every key.
        # That measures the harness during a live stream, not editor delivery.
        from textual.events import Key
        for character in 'draft':
            event = Key(character, character)
            event.set_sender(app)
            app._driver.send_message(event)
        async with asyncio.timeout(4):
            while view.prompt.text != 'draft':
                await asyncio.sleep(.001)
        key_ms = (time.perf_counter()-started)*1000
        assert view.prompt.text == 'draft'
        await until(pilot, lambda: response_painted(app, view, 'STREAM_HEADER_END_PROOF'), 35)
        await until(pilot, lambda: not comms.registry.require('beta').executing)
        assert len(requests) == 1
        assert app._exception is None
    finally:
        if app.frame_profiler is not None:
            app.frame_profiler.disable()
            app.frame_profiler = None
        app.next_frame = None
        (evidence/'active-interactions.json').write_text(json.dumps({
            'sidebar_frames': rows, 'provider_chunks': chunks,
            'scope': 'Actual installed native ACP stream; headless completed frames, not terminal pixels',
            'provider_requests': len(requests), 'input_replays': 0,
        }, indent=2)+'\n')
    (evidence/'typing.json').write_text(json.dumps({'five_key_completion_ms': key_ms,
                                                  'draft_retained': True})+'\n')


if __name__ == '__main__':
    interactive = os.environ.get('STREAM_INTERACTION_TIMING') == '1'
    if interactive:
        from sidebar_collapse_latency_pilot import FrameApp
    asyncio.run(main(app_type=FrameApp if interactive else ToadApp,
                     acceptance=interaction_acceptance if interactive else acceptance, provider_reply=reply,
                     provider_request_budget=1, provider_chunk_characters=25,
                     provider_after_chunk=after_chunk,
                     fixture_stage=Path(os.environ['STREAM_FIXTURE_STAGE'])))
