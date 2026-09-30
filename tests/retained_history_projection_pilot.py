"""Canonical saved-source status follows actual retained coverage publications.

Real Toad application, native journal reader, ACP Agent resource and Textual
history trees. No ACP process, model, provider prompt or public owner starts.
"""
import asyncio
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from agent_comms.comms import Comms
from agent_comms.threads import Thread
from toad.acp.agent import Agent
from toad.agent_schema import AgentDefinition
from toad.app import ToadApp
from toad.widgets.agent_response import AgentResponse
from toad.widgets.session_details import SessionDetails
from toad.widgets.transcript_history import TranscriptHistory


async def main():
    evidence = Path(os.environ['PROJECTION_EVIDENCE']).resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    receipt = {}
    with TemporaryDirectory(prefix='retained-source-', dir=evidence) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / 'wire'),
                          XDG_CONFIG_HOME=str(root / 'config'),
                          XDG_STATE_HOME=str(root / 'state'),
                          XDG_DATA_HOME=str(root / 'data'))
        comms = Comms(root / 'wire')
        comms.messaging.initialize_private_initial_protocol()
        journal = root / 'native.jsonl'
        journal.write_text(''.join(json.dumps({'type': 'message', 'message': {
            'role': 'assistant', 'content': f'## Saved native row {number}\n\n'
            'Canonical retained source owns coverage independently of painted resources.'
        }}) + '\n' for number in range(8)))
        comms.registry.declare(Thread('saved', frozenset(), str(root), session_file=str(journal)))
        page = comms.transcripts.thread_transcript_page('saved')
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(110, 35)) as pilot:
            await app.selected_session.wait_content_ready()
            view = app.selected_session.conversation
            agent = Agent(root, AgentDefinition('retained-source', 'retained-source', {}), None)
            view.set_reactive(type(view).agent, agent)
            await view.transcript.snapshot(page)
            await pilot.pause(.2)
            history = view.contents.query_children(TranscriptHistory).first()
            details = view.query_one(SessionDetails)
            receipt['initial'] = dict(title=details.title, coverage=history.state.reports_coverage)
            assert 'Saved history available' in details.title
            native_children = tuple(history.walk_children())
            pages = tuple(history.pages)
            await history.retire_source(parked=True)
            await view.transcript.reveal_retained(history)
            await pilot.pause()
            receipt['parked'] = dict(title=details.title, coverage=history.state.reports_coverage)
            assert not history.state.reports_coverage
            assert 'Saved history not loaded' in details.title
            await view.transcript.snapshot(page)
            await pilot.pause(.2)
            receipt['validated'] = dict(title=details.title,
                coverage=history.state.reports_coverage, registered=history in view.window.histories,
                pages_retained=tuple(history.pages) == pages,
                native_tree_retained=tuple(history.walk_children()) == native_children)
            (evidence / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
            assert history.state.reports_coverage
            assert 'Saved history available' in details.title, receipt['validated']
            assert 'Saved history available' in details.overview_text
            assert tuple(history.pages) == pages
            assert tuple(history.walk_children()) == native_children
            # A large live message has a real nested rendering pager. It must
            # not certify the saved-source identity when that source is fenced.
            synthetic = AgentResponse('## Paged live message\n\n' + '\n\n'.join(
                f'Live paragraph {i} has its own bounded rendering pager.' for i in range(32)))
            await view.contents.mount(synthetic)
            async with asyncio.timeout(5):
                while not synthetic.query(TranscriptHistory):
                    await pilot.pause(.02)
            await pilot.pause(.1)
            await history.retire_source(parked=True)
            await view.transcript.reveal_retained(history)
            await pilot.pause(.1)
            assert not view.transcript.reports_coverage
            assert 'Saved history not loaded' in details.title
            receipt['nested_rendering_is_not_source_coverage'] = True
            await view.transcript.snapshot(page)
            await pilot.pause(.1)
            assert 'Saved history available' in details.title
            assert tuple(history.pages) == pages
            assert agent.process.process is None and agent.process.runner is None
            assert app._exception is None
        receipt['application_exit'] = 'normal'
    (evidence / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt))


if __name__ == '__main__':
    asyncio.run(main())
