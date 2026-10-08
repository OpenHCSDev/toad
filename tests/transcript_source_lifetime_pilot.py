"""Original source/view and body resources govern retirement and page admission.

Actual Toad/native widget journey; no provider/ACP process or installed claim.
"""
import asyncio
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from agent_comms.comms import Comms
from agent_comms.threads import Thread
from textual.selection import SELECT_ALL
from textual.widgets._markdown import MarkdownParagraph
from toad.app import ToadApp
from toad.widgets.agent_response import AgentResponse
from toad.widgets.transcript_history import TranscriptHistory


async def main():
    evidence = Path(os.environ['SOURCE_LIFETIME_EVIDENCE']).resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='source-lifetime-', dir=evidence) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / 'wire'),
                          XDG_CONFIG_HOME=str(root / 'config'),
                          XDG_STATE_HOME=str(root / 'state'),
                          XDG_DATA_HOME=str(root / 'data'))
        service = Comms(root / 'wire')
        service.messaging.initialize_private_initial_protocol()
        journal = root / 'saved.jsonl'
        journal.write_text(''.join(json.dumps({'type': 'message', 'message': {
            'role': 'assistant', 'content': f'Original native saved row {i}.'
        }}) + '\n' for i in range(4)))
        service.registry.declare(Thread('saved', frozenset(), str(root), session_file=str(journal)))
        page = service.transcripts.thread_transcript_page('saved', max_messages=1)
        assert page.has_older
        app = ToadApp(project_dir=str(root))
        receipt = dict(provider_calls=0,
                       boundary='actual source/Toad/native resources; not installed physical proof')
        async with app.run_test(size=(110, 35)) as pilot:
            await app.selected_session.wait_content_ready()
            view = app.selected_session.conversation
            viewport = view.window.document_viewport
            await viewport.suspend_source()
            short = AgentResponse('Original ordinary native Markdown.\n\nRetained body.', paginate=False)
            long_source = '\n\n'.join(f'Original paged paragraph {i}: native retained source. '
                                      * 3 for i in range(22))
            paged = AgentResponse(long_source)
            await view.contents.mount(short, paged)

            async def ready(body):
                async with asyncio.timeout(10):
                    while not body.body_ready:
                        await pilot.pause(.02)
                await pilot.pause(.05)

            await ready(short)
            await ready(paged)
            assert paged.fragments and paged.fragment_views
            for body in (short, paged):
                await ready(body)
                paragraph = body.query(MarkdownParagraph).first()
                original_children = tuple(body.children)
                app.screen.selections = {paragraph: SELECT_ALL}
                assert not await body.retire_body(), 'Retirement lost original selected text'
                assert tuple(body.children) == original_children
                app.screen.clear_selection()
                async with body._content_lock:
                    assert not await body.retire_body(), 'Retirement crossed a live content mutation'
                body.loading = True
                assert not await body.retire_body(), 'Retirement crossed original Markdown loading'
                body.loading = False
                native_prefix = body._prefix
                source = body.source
                previous_parts = body.fragment_views
                admission = (body.start, body.stop) if previous_parts else None
                assert await body.retire_body()
                assert body.body_dormant and not body.fragment_views
                assert all(prefix in body.children for prefix in native_prefix)
                assert not await body.retire_body(), 'A retired native body admitted retirement twice'
                await body.restore_body()
                await ready(body)
                assert body.source == source and all(prefix in body.children for prefix in native_prefix)
                if previous_parts:
                    assert all(not part.is_attached for part in previous_parts)
                    assert all(part not in previous_parts for part in body.fragment_views)
                    assert (body.start, body.stop) == admission
                receipt['paged_retirement_restore' if previous_parts
                        else 'ordinary_retirement_restore'] = True
            await short.remove()
            await paged.remove()
            receipt['selection_loading_content_custody_preserved'] = True
            cases = []
            for cause in ('current', 'revision', 'edge', 'parked', 'loader'):
                print(json.dumps(dict(starting_source_case=cause)), flush=True)
                entered, release = asyncio.Event(), asyncio.Event()

                async def loader(**bounds):
                    entered.set()
                    await release.wait()
                    return await asyncio.to_thread(service.transcripts.thread_transcript_page,
                                                   'saved', max_messages=1, **bounds)

                history = TranscriptHistory(page, loader)
                # Original admitted source operation prevents automatic edge
                # requests from taking custody before this controlled read.
                history.reserve_source_work()
                await view.contents.mount(history)
                task = asyncio.create_task(history._load_page(True))
                try:
                    await asyncio.wait_for(entered.wait(), 5)
                    original_pages = tuple(history.pages)
                    original_fragments = history.fragment_views
                    if cause == 'revision':
                        history.invalidate_projection()
                    elif cause == 'edge':
                        edge = history.pages[0]
                        async with view.window.history_lock:
                            async with view.window.preserve_history(edge):
                                edge.trim(1, older=True)
                        original_fragments = history.fragment_views
                    elif cause == 'parked':
                        await history.retire_source(parked=True)
                    elif cause == 'loader':
                        async def replacement(**bounds):
                            return await loader(**bounds)
                        history.loader = replacement
                    release.set()
                    result = (await asyncio.wait_for(
                        asyncio.gather(task, return_exceptions=True), 10))[0]
                    if isinstance(result, BaseException):
                        # Closing a replaced source's original prepared scope
                        # cancels its read. This is an explicit terminal
                        # disposition, not permission to publish old content.
                        assert cause != 'current' and isinstance(result, asyncio.CancelledError), result
                    if cause == 'current':
                        assert len(history.pages) > len(original_pages)
                    else:
                        assert tuple(history.pages) == original_pages
                        assert history.fragment_views == original_fragments
                    cases.append(dict(cause=cause, accepted=cause == 'current',
                                      native_page_count=len(history.pages),
                                      read_disposition='cancelled' if isinstance(result, asyncio.CancelledError)
                                      else 'completed'))
                finally:
                    release.set()
                    if not task.done():
                        await asyncio.wait_for(task, 10)
                    await history.remove()
                    await pilot.pause(.02)
            receipt['original_page_admission_cases'] = cases
            async def completed_loader(**bounds):
                return await asyncio.to_thread(service.transcripts.thread_transcript_page,
                                               'saved', max_messages=1, **bounds)
            scheduled = TranscriptHistory(page, completed_loader)
            await view.contents.mount(scheduled)
            scheduled._request_page(True)
            async with asyncio.timeout(10):
                while len(scheduled.pages) < 2 or not scheduled.checkpoint_available:
                    await pilot.pause(.02)
            receipt['original_worker_admission_executed'] = True
            await scheduled.remove()
            assert app._exception is None
        assert app._exception is None
        receipt['native_shutdown_clean'] = True
        (evidence / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
        print(json.dumps(receipt), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
