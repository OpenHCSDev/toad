"""Installed real saved-backend tabs and lazy PageDown; never submit or stop owners."""

import asyncio
from hashlib import sha256
from importlib.resources import files
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from importlib.metadata import distribution
from dataclasses import fields
import sys

import psutil
from agent_comms.comms import wire
from toad.app import ToadApp
from toad.agent_schema import AgentDefinition
from toad.transcript_state import WorkingTranscript
from toad.widgets.transcript_history import TranscriptHistory
from toad.widgets.conversation import Conversation
from toad.widgets.session_tabs import SessionLabel
from toad.transcript_preparation import PageRequest, TranscriptPageWork
from saved_state_user_journey_pilot import click_thread
from viewport_recent_tabs_pilot import ReaderCheckpoint


class SavedReaderApp(ToadApp):
    CSS_PATH = [files("toad").joinpath("toad.tcss"), files("toad").joinpath("screens/comms.tcss")]
    phase = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.frames = []

    def checkpoint(self, label):
        evidence = Path(os.environ["READONLY_READER_EVIDENCE"])
        (evidence / "frames.json").write_text(json.dumps(self.frames, indent=2))
        print(label, len(self.frames), flush=True)

    def _display(self, screen, renderable):
        super()._display(screen, renderable)
        if self.phase is None or renderable is None or self._batch_count:
            return
        session = self.selected_session
        view = session.query_one_optional(Conversation)
        if view is None:
            self.frames.append(dict(clock=monotonic(), phase=self.phase,
                                    source=session.id, body_nonwhite=0))
            return
        window = view.window
        region = window.scrollable_content_region
        strips = screen._compositor.render_strips()
        body = "\n".join(strip.crop(region.x, region.right).text
                         for strip in strips[region.y:region.bottom])
        histories = tuple(window.histories)
        self.frames.append(dict(clock=monotonic(), phase=self.phase,
                                source=session.id,
                                y=window.scroll_y, maximum=window.max_scroll_y,
                                follows_tail=window.follows_tail,
                                body_hash=sha256(body.encode()).hexdigest(),
                                body_nonwhite=len("".join(body.split())),
                                has_newer=any(history.has_newer for history in histories),
                                loading=any(isinstance(history.state, WorkingTranscript)
                                            for history in histories)))


async def until(pilot, app, condition):
    async with asyncio.timeout(20):
        while not condition():
            if app._exception is not None:
                raise app._exception
            await pilot.pause(.03)


async def ready(pilot, app, source):
    await until(pilot, app, lambda: source.query(Conversation))
    view = source.query_one(Conversation)
    await until(pilot, app, lambda: view.agent_ready)
    await pilot.pause()
    return view


async def select(app, pilot, source):
    label = app.screen.query_one(f"SessionLabel#{source.id}", SessionLabel)
    label.scroll_visible(animate=False, immediate=True)
    await pilot.pause()
    started = monotonic()
    assert await pilot.click(label)
    await until(pilot, app, lambda: app.selected_session is source)
    await ready(pilot, app, source)
    return started


async def record_retained_validation(source, view, history, reader, page, evidence):
    current_view = source.conversation
    current_histories = tuple(current_view.window.histories)
    current_page = await current_view.agent.get_transcript_page()
    previous_page = page.page
    differences = []
    for index, (previous, current) in enumerate(zip(previous_page.events, current_page.events)):
        if previous != current:
            differences.append(dict(index=index, previous=type(previous).__name__,
                                    current=type(current).__name__,
                                    fields=[field.name for field in fields(previous)
                                            if type(previous) is type(current)
                                            and getattr(previous, field.name) != getattr(current, field.name)]))
    (evidence/'retained-validation.json').write_text(json.dumps(dict(
        view_reused=current_view is view, old_attached=history.is_attached,
        old_registered=history in current_histories,
        old_state=type(history.state).__name__, old_scope_closed=reader.closed,
        old_through=repr(history.through), old_after=repr(previous_page.after),
        new_after=repr(current_page.after), old_events=len(previous_page.events),
        new_events=len(current_page.events), differences=differences,
        attached_histories=[dict(state=type(h.state).__name__, registered=h in current_histories,
                                original=h is history, through=repr(h.through))
                           for h in current_view.contents.query(TranscriptHistory)]), indent=2)+'\n')


async def warm_pages(app, pilot, first, second, evidence, checkpoint, *, undo_text=None):
    """Original native source, real tab clicks and final parked disposal."""
    view = second.conversation
    source_name = second.id
    window = view.window
    await until(pilot, app, lambda: all(h.state.accepts_source_work for h in window.histories))
    # Borrow the witness acquired before leaving the source, never recapture a
    # baseline from a potentially rebuilt return.
    await checkpoint.verify(app, pilot)
    history = next(iter(window.histories))
    reader = history._reader()
    request = PageRequest(before=history.pages[0].page.before)
    await reader.get(request)
    key = TranscriptPageWork(reader.scope, reader.loader, reader.through, request).work_key
    prepared = app.preparation._ready[key][0]
    page = history.pages[0]
    visible = app.screen._compositor.visible_widgets
    cached_strips = tuple((node, y, strip) for node in page.walk_children()
                          if node in visible for y, strip in node._styles_cache._cache.items())
    records = []
    try:
        for index in range(2):
            reads_before = await checkpoint.page_reads()
            app.phase = f'warm-away-{index}'
            await select(app, pilot, first)
            assert not reader.closed, 'Leaving an actual saved-source tab closed its prepared scope'
            app.phase = f'warm-return-{index}'
            started = await select(app, pilot, second)
            try:
                await until(pilot, app, lambda: history.state.accepts_source_work or not history.is_attached)
            except TimeoutError:
                await record_retained_validation(second, view, history, reader, page, evidence)
                raise
            if not history.is_attached:
                await record_retained_validation(second, view, history, reader, page, evidence)
                raise AssertionError('The native return retired the original retained history; see retained-validation.json')
            current = history._reader()
            await current.get(request)
            await checkpoint.verify(app, pilot)
            read_delta = await checkpoint.page_reads() - reads_before
            assert read_delta == 0, ('Configured warm return reacquired raw history', read_delta)
            displayed = [frame for frame in app.frames
                         if frame['phase'] == app.phase and frame['source'] == source_name]
            records.append(dict(reader_reused=current is reader,
                                prepared_reused=app.preparation._ready.get(key, (None,))[0] is prepared,
                                unchanged_page_fragment_editor_reader_render_resources=True,
                                raw_page_read_delta=read_delta,
                                non_tail_preserved=not checkpoint.follows_tail,
                                observed_native_strip_lines=len(cached_strips),
                                reused_native_strip_lines=sum(node._styles_cache._cache.get(y) is strip
                                                              for node, y, strip in cached_strips),
                                completed_frames=len(displayed),
                                all_frames_readable=bool(displayed) and all(f['body_nonwhite'] for f in displayed),
                                first_completed_body_frame_ms=(displayed[0]['clock']-started)*1000 if displayed else None,
                                within_budget=app.preparation.retained_bytes <= app.preparation.max_bytes))
        if undo_text is not None:
            editor = second.conversation.prompt.prompt_text_area
            editor.scroll_visible(animate=False, immediate=True)
            await pilot.pause()
            assert await pilot.click(editor), 'Configured warm-return editor is not clickable'
            await pilot.press('ctrl+z')
            assert editor.text == undo_text
            # PromptAction reserves Ctrl+Y for Send now. Borrow the original
            # native editor redo owner without invoking a submission binding.
            editor.redo()
            assert editor.text == checkpoint.text
            assert editor.document is checkpoint.document and editor.history is checkpoint.history
    finally:
        # Auxiliary cache witnesses end before parked disposal. The caller
        # releases its borrowed checkpoint before any subsequent journey.
        del cached_strips, prepared, page
    app.phase = 'dispose-parked-original'
    await select(app, pilot, first)
    closer = app.screen.query_one(f'#close-{second.id}')
    closer.scroll_visible(animate=False, immediate=True)
    await pilot.pause()
    assert await pilot.click(closer)
    await until(pilot, app, lambda: second.id not in app.workspace_sessions.views)
    receipt = dict(pins={name: json.loads(distribution(name).read_text('direct_url.json'))
                         for name in ('batrachian-toad', 'agent-comms', 'textual')},
                   returns=records, final_scope_closed=reader.closed,
                   final_prepared_retained=key in app.preparation._ready,
                   final_history_attached=history.is_attached,
                   boundary='Actual installed original native/ACP and Pilot tab clicks/completed compositor frames; no LinuxDriver video or source mutation.')
    (evidence/'warm-pages.json').write_text(json.dumps(receipt, indent=2)+'\n')
    assert all(all(row[k] for k in ('reader_reused','prepared_reused',
                                  'unchanged_page_fragment_editor_reader_render_resources','all_frames_readable',
                                  'within_budget')) for row in records), records
    assert reader.closed and key not in app.preparation._ready and not history.is_attached


async def main():
    evidence = Path(os.environ["READONLY_READER_EVIDENCE"])
    evidence.mkdir(parents=True, exist_ok=True)
    # Resolve the approved default route once. No owner start/stop or fixture
    # teardown: this app must never use runtime_fixture.ToadApp on the live root.
    comms = wire()
    names = ("agent-comms-ux", "nra-architecture")
    owners = {name: psutil.Process(comms.registry.require(name).pid) for name in names}
    identities = {name: (p.pid, p.create_time()) for name, p in owners.items()}
    assert all(p.is_running() for p in owners.values())
    print("READONLY_EXISTING_OWNERS_CONFIRMED", identities, flush=True)
    app = None
    try:
        with TemporaryDirectory(prefix="readonly-reader-", dir=os.environ["TMPDIR"]) as directory:
            root = Path(directory)
            os.environ.update(XDG_CONFIG_HOME=str(root / "config"),
                              XDG_STATE_HOME=str(root / "state"),
                              XDG_DATA_HOME=str(root / "data"))
            definition = AgentDefinition.decode(dict(
                name="Agent Comms", identity="saved-reader-check", short_name="agent",
                protocol="acp", run_command={"*": str(Path(sys.executable).with_name('agent-comms-acp'))}))
            app = SavedReaderApp(agent_data=definition,
                                project_dir=comms.registry.require(names[0]).worktree,
                                agent_session_id=names[0])
            async with app.run_test(size=(140, 36)) as pilot:
                first = app.selected_session
                await ready(pilot, app, first)
                app.checkpoint("FIRST_ACTUAL_SAVED_READY")
                second = await click_thread(app, pilot, names[1], "#nra")
                view = await ready(pilot, app, second)
                app.checkpoint("SECOND_ACTUAL_SAVED_READY")
                if os.environ.get('READONLY_WARM_PAGES_ONLY') == '1':
                    checkpoint = await ReaderCheckpoint.capture(second, app, pilot)
                    try:
                        await warm_pages(app, pilot, first, second, evidence, checkpoint)
                    finally:
                        del checkpoint
                        app.checkpoint('ORIGINAL_WARM_PAGES_FINAL')
                    return
                window = view.window
                app.phase = "reader-input"
                window.focus(scroll_visible=False)
                await pilot.press("up", "up", "up", "up", "up")
                await pilot.wait_for_scheduled_animations()
                await pilot.pause()
                position = window.scroll_y
                assert not window.follows_tail
                reader_paint = app.frames[-1]["body_hash"]
                app.checkpoint("READER_OFFSET_ESTABLISHED")
                history = next(iter(window.histories))
                app.phase = "physical-A"
                await select(app, pilot, first)
                app.phase = "physical-B-return"
                await select(app, pilot, second)
                assert view is second.conversation and history in window.histories
                assert window.scroll_y == position and not window.follows_tail
                returned = [frame for frame in app.frames
                            if frame["phase"] == "physical-B-return"
                            and frame["source"] == names[1]]
                assert returned and all(frame["body_hash"] == reader_paint
                                        for frame in returned), "Warm return changed reader paint"
                app.checkpoint("PHYSICAL_ABA_RETAINED_READER")

                # Primary case: ordinary PageDown at lazy/not fully prepared
                # bottom. End is deliberately absent until after reverse/idle.
                app.phase = "repeated-pagedown-lazy-bottom"
                window.focus(scroll_visible=False)
                await pilot.press(*(["pageup"] * 5))
                for _ in range(30):
                    await pilot.press("pagedown")
                app.checkpoint("REPEATED_PAGEDOWN_LAZY_BOTTOM_SENT")
                await pilot.wait_for_scheduled_animations()
                app.phase = "reverse"
                await pilot.press(*(["pageup"] * 8))
                await pilot.wait_for_scheduled_animations()
                app.phase = "idle"
                await pilot.pause(.4)
                app.checkpoint("REVERSE_IDLE_COMPLETE")
                app.phase = "separate-End"
                await pilot.press("end")
                await pilot.pause(.3)
                assert window.follows_tail
                assert app._exception is None
                observed = app.frames
                app.checkpoint("SEPARATE_END_COMPLETE")
                assert observed and all(frame["body_nonwhite"] for frame in observed), "Blank destination frame"
                assert all(0 <= frame["y"] <= frame["maximum"] for frame in observed), "Scroll beyond canonical extent"
                primary = [frame for frame in observed
                           if frame["phase"] == "repeated-pagedown-lazy-bottom"]
                assert any(frame["loading"] and frame["has_newer"]
                           for frame in primary), "PageDown missed an admitted lazy edge read"
                assert len({frame["maximum"] for frame in primary}) > 1, \
                    "PageDown did not exercise a changing native extent"
            await asyncio.get_running_loop().shutdown_default_executor()
    finally:
        if app is not None:
            (evidence / "frames.json").write_text(json.dumps(app.frames, indent=2))
        final = {name: (p.pid, p.create_time()) for name, p in owners.items() if p.is_running()}
        (evidence / "owners.json").write_text(json.dumps(dict(before=identities, after=final), indent=2))
        assert identities == final, "Live owner identity changed during read-only UI journey"
    print("INSTALLED_READONLY_SAVED_ABA_PAGEDOWN_REVERSE_IDLE_END_PASS")


async def private_original_warm(app, pilot, service, project, evidence):
    """Reuse the declared original capture and current-format private fixture."""
    from toad.navigation_target import channel_target, NavigationContext

    os.environ['READONLY_READER_EVIDENCE'] = str(evidence)
    original = app.selected_session
    view = original.conversation
    await until(pilot, app, lambda: all(h.state.accepts_source_work for h in view.window.histories))
    window = view.window
    editor = view.prompt.prompt_text_area
    assert await pilot.click(editor), 'Private configured composer is not clickable'
    editor.insert('configured native draft')
    editor.history.checkpoint()
    editor.insert(' with undo')
    await until(pilot, app, lambda: window.max_scroll_y > 0)
    window.release_anchor()
    window.scroll_to(y=min(5, window.max_scroll_y - 1), animate=False, immediate=True)
    await until(pilot, app, lambda: not window.follows_tail)
    checkpoint = await ReaderCheckpoint.capture(original, app, pilot)
    try:
        assert not checkpoint.follows_tail, 'Configured checkpoint requires a genuine non-tail reader'
        reads_before = await checkpoint.page_reads()
        user = service.messaging.user_identity(str(project)).name
        await channel_target('#retained').open(NavigationContext(
            app, original.id, project, user))
        channel = app.selected_session
        await channel.wait_content_ready()
        await select(app, pilot, original)
        await checkpoint.verify(app, pilot)
        assert await checkpoint.page_reads() == reads_before, 'First configured return reacquired raw history'
        await warm_pages(app, pilot, channel, original, evidence,
                         checkpoint,
                         undo_text='configured native draft')
    finally:
        del checkpoint
        app.checkpoint('PRIVATE_ORIGINAL_WARM_PAGES_FINAL')


if __name__ == "__main__":
    if sys.argv[1:] == ['--private-original-warm']:
        from original_turn_resource_real_installed_pilot import main as retained_fixture
        asyncio.run(retained_fixture(readonly_acceptance=private_original_warm,
                                     app_type=SavedReaderApp))
    else:
        asyncio.run(main())
