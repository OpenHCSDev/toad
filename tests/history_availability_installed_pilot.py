"""Replay a captured real ACP saved page through the installed UI, without input."""
import asyncio
import json
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
            await view.on_transcript_snapshot(TranscriptSnapshotUpdate(page))
            await pilot.pause()
            source = view.query_one(TranscriptHistory)
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
