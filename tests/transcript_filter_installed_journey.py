"""Physical Pi saved-state -> installed filter controls -> painted reader journey.

Reuse the maintained native/loopback fixture. No Agent/UI/loader/renderer
patches; the only controlled responses are the local provider's text.
"""

import asyncio
import json
import os
from pathlib import Path

from acp.schema import TextContentBlock
from agent_comms.acp import CommsClient
from l0a_native_installed_pilot import main as native_fixture, until
from native_session_retention_pilot import InstalledApp, conversation_paint
from saved_state_user_journey_pilot import SavedStateSubscriber
from textual.widgets import Checkbox
from toad.widgets.message_filter import AgentCategory, MessageCategory, all_categories
from toad.widgets.side_bar import SideBar, SideBarCollapsible
from toad.widgets.thread_comms import ThreadCommsSidebar


def paragraphs(prefix, number, count=100):
    return '\n\n'.join(f'{prefix}_{number}_{row:03d} '+ 'saved native reader text ' * 6
                       for row in range(count))


def reply(request, number):
    return ({'role': 'assistant',
             'reasoning_content': paragraphs('SAVED_THOUGHT', number, 60),
             'content': paragraphs('SAVED_ANSWER', number)}, 'stop')


async def prepare(comms, project, requests, entered, release, hold_next):
    release.set()
    client = CommsClient(comms, runtime_enabled=True,
        private_nk_native_package=Path(os.environ['AC_NATIVE_COPIED_PACKAGE']),
        private_nk_wire_root_id=os.environ['AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID'])
    subscriber = SavedStateSubscriber()
    client.on_connect(subscriber)
    try:
        await client.load_session(cwd=str(project), session_id='beta')
        for number in range(2):
            async with asyncio.timeout(20):
                await client.prompt('beta', [TextContentBlock(type='text',
                    text=paragraphs('SAVED_PROMPT', number))])
            subscriber.require_success()
        assert len(requests) == 2
        native = Path(comms.registry.require('beta').session_file).read_text()
        assert 'SAVED_THOUGHT_1_000' in native and 'SAVED_ANSWER_2_099' in native
        print('ACTUAL_PI_SAVED_THINKING_AND_MESSAGES', len(requests), flush=True)
    finally:
        await client.shutdown()


async def choose(app, pilot, selected):
    sidebar = app.screen.query_one('#thread-sidebar', SideBar)
    sidebar.reveal()
    await sidebar.wait_content_ready()
    tree = sidebar.query_one(ThreadCommsSidebar)
    tree.query_ancestor(SideBarCollapsible).collapsed = False
    await pilot.pause()
    for category in MessageCategory.members_with(MessageCategory):
        checkbox = tree.query_one(f'#filter-{category.declared_name}', Checkbox)
        if checkbox.value == (category in selected):
            continue
        checkbox.scroll_visible(animate=False, immediate=True)
        await pilot.pause()
        assert await pilot.click(checkbox), f'Filter {category.declared_name} not clickable'
        await until(pilot, lambda: checkbox.value == (category in selected))
    await until(pilot, lambda: app.selected_session.conversation.visible_categories == selected)


async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    from toad.transcript_filter import RequestedScanDemand
    from toad.widgets.transcript_history import TranscriptHistory

    view = app.selected_session.conversation
    try:
        await until(pilot, lambda: 'SAVED_THOUGHT_2_059' in conversation_paint(app.screen))
    except TimeoutError:
        print('STARTUP_CROPPED_PAINT', repr(conversation_paint(app.screen)), flush=True)
        print('STARTUP_FRAME', repr('\n'.join(strip.text for strip in app.screen._compositor.render_strips())), flush=True)
        print('STARTUP_HISTORY', [(h.state.declared_name, h.fragment_count, h.pages[-1].stop,
              len(h.pages[-1].fragments)) for h in view.contents.query(TranscriptHistory)],
              view.window.scroll_y, view.window.max_scroll_y, flush=True)
        raise
    canonical = next(history for history in view.contents.query(TranscriptHistory)
                     if history.parent is view.contents)
    assert isinstance(canonical, TranscriptHistory)
    original_page = canonical.pages[-1].page
    native_file = Path(comms.registry.require('beta').session_file)
    native_bytes = native_file.read_bytes()
    editor = view.prompt.prompt_text_area
    editor.insert('Reader draft stays with original document')
    editor.history.checkpoint()
    editor.insert(' and undo')
    document, undo, draft = editor.document, editor.history, editor.text
    original_mode = app.selected_mode
    print('INSTALLED_SAVED_TAIL_PAINT_AND_EDITOR_CAPTURED', flush=True)

    await choose(app, pilot, frozenset({AgentCategory}))
    view.window.release_anchor()
    view.window.scroll_to(y=0, animate=False, immediate=True)
    await until(pilot, lambda: 'SAVED_ANSWER_2_099' in conversation_paint(app.screen), seconds=20)
    assert 'SAVED_THOUGHT_' not in conversation_paint(app.screen)
    projection = canonical.filter.overlay
    assert projection is not None
    source = projection._reader()
    assert canonical.pages[-1].page is original_page
    assert projection.fragment_count <= projection.fragment_limit
    print('REAL_CHECKBOX_FILTER_REVEALS_SAVED_OLDER_ANSWER_PAINT', flush=True)

    # A declared request case inherits admission/worker/pager/retirement. This
    # extension needs no consumer switch or additional member roster.
    class ReaderEarlierDemand(RequestedScanDemand):
        pass

    canonical.filter.demand = ReaderEarlierDemand()
    await until(pilot, lambda: not canonical.filter.scanning and projection.older_page_available)
    worker = canonical.filter.start_scan()
    assert worker is not None, 'Declared demand failed to admit real earlier page'
    await worker.wait()
    print('DECLARATION_ONLY_SCAN_DEMAND_USES_ACTUAL_INSTALLED_PAGER', flush=True)

    # Exercise cancellation before worker entry on the actual mounted history.
    await until(pilot, lambda: not canonical.filter.scanning)
    canonical.filter.changed()
    worker = canonical.filter.start_scan()
    assert worker is not None, 'No real queued worker to test pre-entry cancellation'
    worker.cancel()
    assert worker.is_cancelled
    assert not canonical.filter.scanning, 'Cancelled worker stranded scan admission'
    await pilot.pause()
    await choose(app, pilot, frozenset())
    await until(pilot, lambda: canonical.filter.overlay is None and source.closed)
    assert not canonical.older.display and not canonical.newer.display
    assert not canonical.filter.scanning
    print('EMPTY_SELECTION_RETIRES_READER_AND_CANCELLED_WORKER', flush=True)

    await choose(app, pilot, frozenset({AgentCategory}))
    view.window.scroll_to(y=0, animate=False, immediate=True)
    await until(pilot, lambda: 'SAVED_ANSWER_2_099' in conversation_paint(app.screen), seconds=20)
    await pilot.resize_terminal(112, 34)
    await pilot.press('pagedown', 'pageup')
    other = await app.new_session_screen(app.get_main_screen)
    await pilot.pause()
    other_view = app.selected_session.conversation
    other_view.prompt.focus()
    await pilot.press('x')
    assert other_view.prompt.text == 'x'
    await app.switch_mode(original_mode)
    await pilot.pause()
    assert view.visible_categories == frozenset({AgentCategory})
    await app.close_session_mode(other.mode_name)
    await choose(app, pilot, all_categories())
    view.window.anchor()
    await until(pilot, lambda: 'SAVED_THOUGHT_2_059' in conversation_paint(app.screen), seconds=20)
    assert canonical.filter.overlay is None
    assert editor.document is document and editor.history is undo and editor.text == draft
    assert native_file.read_bytes() == native_bytes
    assert len(requests) == 2, 'Filtering sent an input or called provider'
    assert app._exception is None
    print('PASS_REAL_SAVED_FILTER_RETURN_PAINT_RESIZE_TAB_EDITOR_NO_REPLAY', flush=True)


if __name__ == '__main__':
    asyncio.run(native_fixture(app_type=InstalledApp, provider_reply=reply,
                              prepare_state=prepare, acceptance=acceptance))
