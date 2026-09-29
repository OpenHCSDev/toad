"""Replay a captured real ACP saved page through the installed UI, without input."""
import asyncio
import json
import re
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from agent_comms.field_codec import FieldCodec
from agent_comms.transcripts import TranscriptPage
from agent_comms.acp_extension import TranscriptSnapshotUpdate
from toad.acp.agent import Agent
from toad.widgets.session_details import SessionDetails
from toad.widgets.transcript_history import TranscriptHistory
from runtime_fixture import ToadApp

async def main():
    payload = None
    for line in Path(sys.argv[1]).read_text().splitlines():
        if not line.startswith('[agent] '):
            continue
        envelope = json.loads(line[len('[agent] '):])
        updates = envelope.get('params', {}).get('update', {}).get('_meta', {}).get('agentComms', {}).get('updates', [])
        for update in updates:
            if update['kind'] == 'transcript_snapshot':
                payload = update['page']
                break
        if payload is not None:
            break
    assert payload is not None
    page = FieldCodec.decode(TranscriptPage, payload)
    with TemporaryDirectory(prefix='history-label-', dir='.artifacts') as directory:
        root = Path(directory).resolve()
        os.environ.update(AGENT_COMMS_ROOT=str(root/'wire'), XDG_CONFIG_HOME=str(root/'config'),
                          XDG_STATE_HOME=str(root/'state'), XDG_DATA_HOME=str(root/'data'))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(140, 42)) as pilot:
            await pilot.pause()
            view = app.screen.conversation
            agent = Agent(root, {'identity': 'saved-page-proof', 'name': 'Saved page proof', 'run_command': {'*': ''}}, None, None)
            view.agent = agent
            details = view.query_one(SessionDetails)
            view.native_history_status = 'unavailable'
            await pilot.pause()
            assert 'Bus input verification unavailable' in details.title
            assert 'Saved history not loaded' in details.title
            await view.transcript.snapshot(page)
            await pilot.pause()
            source = view.query_one(TranscriptHistory)
            await pilot.pause(1)
            from toad.widgets.agent_response import AgentResponse
            frame = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
            print("GEOMETRY", view.region, view.window.region, view.contents.region, source.region, "scroll", view.window.scroll_y, view.window.max_scroll_y)
            print("STYLES", [(type(w).__name__, str(w.styles.height), str(w.styles.min_height), str(w.styles.max_height), str(w.styles.layout), w.is_container, w.BLANK, w.virtual_size) for w in (view.window, view.contents, source, *source.pages)])
            print("PAGES", [(len(p.fragments), p.start, p.stop, p.region, p.display) for p in source.pages])
            print("RESPONSES", [(len(r.source), r.region, r.display, r in app.screen._compositor.visible_widgets, r.body_ready, r.body_dormant) for r in source.query(AgentResponse)])
            print("FRAME_NONSPACE", len(frame.strip()), "WINDOW_TEXT", sum(len(strip.text.strip()) for strip in app.screen._compositor.render_strips()[view.window.region.y:view.window.region.bottom]))
            visible_responses = [r for r in source.query(AgentResponse)
                                 if r in app.screen._compositor.visible_widgets
                                 and r.region.overlaps(view.window.region)]
            assert source.region.height > 0 and view.contents.region.height > 0
            assert visible_responses, "Saved response must actually intersect the viewport"
            window_frame = "\n".join(strip.crop(view.window.region.x, view.window.region.right).text
                                     for strip in app.screen._compositor.render_strips()[view.window.region.y:view.window.region.bottom])
            response_words = {word.lower() for r in visible_responses
                              for word in re.findall(r"[A-Za-z]{8,}", r.source)}
            painted_words = response_words.intersection(re.findall(r"[a-z]{8,}", window_frame.lower()))
            assert len(painted_words) >= 3, "Actual saved response words must be painted inside Window"
            print("ACTUAL_SAVED_WORDS_PAINTED", len(painted_words))
            from toad.block_navigation import ConversationBlock
            from textual.widget import Widget
            from textual.dom import DOMNode
            assert not issubclass(ConversationBlock, DOMNode)
            for block in ConversationBlock.__subclasses__():
                native_base = next(base for base in block.__bases__ if issubclass(base, Widget))
                assert block._css_bases(block)[1] is native_base
            app.save_screenshot("retained-fixed.svg", path=".artifacts")
            assert source.state.reports_coverage
            assert 'Saved history available' in details.title
            assert 'Bus input verification unavailable' in details.title
            assert 'History unavailable' not in details.title
            for status in ('none', 'coverage_only', 'proven', 'unavailable'):
                view.native_history_status = status
                await pilot.pause()
                assert 'Saved history available' in details.title
                assert ('Bus input verification unavailable' in details.title) == (status == 'unavailable')
            details.collapsed = False
            await pilot.pause()
            assert 'check the ACP log' in str(details.history.render())
            assert 'Saved history available' in details.overview_text
            assert not agent.permissions.pending
            assert app._exception is None
        print(f'PASS: installed captured ACP snapshot {len(page.events)} events; saved history available independently of all typed cursor statuses')
        print('No prompt, native-owner restart, live installation/history write, or live provider call')

if __name__ == '__main__':
    asyncio.run(main())
