"""Actual tab return must retain bounded prepared pages and native rendered bodies.

Private native journals and the real application/renderer execute; no ACP process
or provider starts. This resource gate precedes installed original-history proof.
"""
import asyncio
from importlib.metadata import distribution
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic

import toad

from agent_comms.comms import Comms
from agent_comms.threads import Thread
from toad.app import ToadApp
from toad.transcript_preparation import PageRequest, TranscriptPageWork
from toad.widgets.session_tabs import SessionLabel
from toad.widgets.transcript_history import TranscriptHistory, TranscriptFragmentView


async def select(app, pilot, identity):
    label = app.screen.query_one(f"SessionLabel#{identity}", SessionLabel)
    label.scroll_visible(animate=False, immediate=True)
    await pilot.pause()
    assert await pilot.click(label)
    async with asyncio.timeout(5):
        while app.selected_session.id != identity:
            await pilot.pause(.01)
    await pilot.pause(.05)


async def main():
    evidence = Path(os.environ['PAGE_SCOPE_EVIDENCE'])
    evidence.mkdir(parents=True, exist_ok=True)
    receipt = {'pins': {name: json.loads(distribution(name).read_text('direct_url.json'))
                       for name in ('batrachian-toad', 'agent-comms', 'textual')},
               'toad_module': str(Path(toad.__file__).resolve()),
               'boundary': 'Actual private native source and resource journey, no ACP/provider/original root.'}
    with TemporaryDirectory(prefix='warm-pages-', dir=evidence) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root/'wire'), XDG_CONFIG_HOME=str(root/'config'),
                          XDG_STATE_HOME=str(root/'state'), XDG_DATA_HOME=str(root/'data'))
        comms = Comms(root/'wire')
        comms.messaging.initialize_private_initial_protocol()
        source = root/'saved.jsonl'
        source.write_text(''.join(json.dumps({'type': 'message', 'message': {
            'role': 'assistant', 'content': f'## Saved row {i}\n\n'+('Native prepared paragraph. '*15)}})
            +'\n' for i in range(60)))
        comms.registry.declare(Thread('saved', frozenset(), str(root), session_file=str(source)))

        async def loader(**kwargs):
            return await asyncio.to_thread(comms.transcripts.thread_transcript_page, 'saved', **kwargs)

        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(120, 35)) as pilot:
            first = app.selected_session
            await first.wait_content_ready()
            view = first.conversation
            page = await loader()
            history = TranscriptHistory(page, loader=loader)
            await view.contents.mount(history)
            await pilot.pause(.2)
            reader = history._reader()
            request = PageRequest(before=page.before)
            await reader.get(request)
            key = TranscriptPageWork(reader.scope, loader, reader.through, request).work_key
            prepared = app.preparation._ready[key][0]
            bodies = tuple(view.query(TranscriptFragmentView))
            native_children = tuple(tuple(body.children) for body in bodies)
            editor = view.prompt.prompt_text_area
            await pilot.click(editor)
            await pilot.press('d', 'r', 'a', 'f', 't', 'left', 'backspace', 'ctrl+z')
            draft, document, undo = editor.text, editor.document, editor.history
            y, follow = view.window.scroll_y, view.window.follows_tail
            second = await app.session_navigation.new(app.session_navigation.default_source)
            await pilot.pause(.05)
            receipt['parked'] = {'scope_closed': reader.scope.closed,
                                 'prepared_page_retained': key in app.preparation._ready}
            records = []
            for _ in range(2):
                started = monotonic()
                await select(app, pilot, first.id)
                returned = history._reader()
                reads_before = comms.transcripts.page_reads
                await returned.get(request)
                records.append(dict(reader_reused=returned is reader,
                                    request_native_reads=comms.transcripts.page_reads - reads_before,
                                    prepared_page_reused=app.preparation._ready.get(key, (None,))[0] is prepared,
                                    native_body_reused=tuple(view.query(TranscriptFragmentView)) == bodies,
                                    native_children_reused=tuple(tuple(body.children) for body in bodies) == native_children,
                                    editor_reused=editor.document is document and editor.history is undo,
                                    draft_preserved=editor.text == draft,
                                    reader_preserved=(view.window.scroll_y, view.window.follows_tail) == (y, follow),
                                    settled_return_ms=(monotonic()-started)*1000,
                                    retained_bytes=app.preparation.retained_bytes,
                                    within_budget=app.preparation.retained_bytes <= app.preparation.max_bytes))
                await select(app, pilot, second.mode_name)
            # An actual new native source boundary must revoke the old scope.
            await select(app, pilot, first.id)
            with source.open('a') as stream:
                stream.write(json.dumps({'type': 'message', 'message': {
                    'role': 'assistant', 'content': 'New committed native source row'}})+'\n')
            advanced = await loader()
            history.retain_committed(advanced.after)
            replacement = history._reader()
            await replacement.get(request)
            replacement_key = TranscriptPageWork(
                replacement.scope, loader, replacement.through, request).work_key
            receipt['source_advance'] = dict(old_scope_closed=reader.scope.closed,
                                             old_page_retained=key in app.preparation._ready,
                                             reader_replaced=replacement is not reader,
                                             new_page_retained=replacement_key in app.preparation._ready)
            await select(app, pilot, second.mode_name)
            # Close a parked resource through its actual owning lifecycle.
            await history.retire_source()
            receipt['final_retirement'] = {'scope_closed': replacement.scope.closed,
                                           'prepared_page_retained': replacement_key in app.preparation._ready}
            receipt['returns'] = records
            assert app._exception is None
        receipt['application_exit'] = 'normal'
    (evidence/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    assert not receipt['parked']['scope_closed'], 'Tab parking revoked prepared-page lifetime'
    assert receipt['parked']['prepared_page_retained'], 'Tab parking discarded adjacent prepared pages'
    assert all(all(row[key] for key in ('reader_reused', 'prepared_page_reused', 'native_body_reused',
                                      'native_children_reused', 'editor_reused', 'draft_preserved',
                                      'reader_preserved', 'within_budget')) for row in receipt['returns']), receipt['returns']
    assert receipt['final_retirement']['scope_closed']
    assert not receipt['final_retirement']['prepared_page_retained']
    assert all(row['request_native_reads'] == 0 for row in receipt['returns'])
    assert receipt['source_advance'] == dict(old_scope_closed=True, old_page_retained=False,
                                            reader_replaced=True, new_page_retained=True)
    print('RETAINED_PAGE_SCOPE_NATIVE_BODY_EDITOR_RETIREMENT_PASS')


if __name__ == '__main__':
    asyncio.run(main())
