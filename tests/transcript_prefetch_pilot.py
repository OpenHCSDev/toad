"""Lookahead is worker-owned data: bounded, shared, cancellable, never mounted."""

import asyncio
import threading
import sys
from pathlib import Path
from unittest.mock import patch

from agent_comms.transcripts import TranscriptCursor, TranscriptPage
from agent_comms.transcript_events import AssistantTranscript, ToolStartTranscript, UserTranscript

from toad.transcript_preparation import (
    CategoryProjection, PageRequest, PreparedTranscriptPage,
    ProjectedTranscriptSource, TranscriptPageBuffer,
)
from toad.widgets.message_filter import AgentCategory, UserCategory, all_categories
from toad.widgets.transcript_fragments import transcript_fragments
from toad.work_preparation import PreparationRuntime


def cursor(offset):
    return TranscriptCursor("fixture", offset)


def page(before, after, *, text=None):
    return TranscriptPage((AssistantTranscript(text or f'Page {before}\n\n' + '- row\n' * 25),),
                          cursor(before), cursor(after), before > 0, after < 1000)


class Renderer:
    def __init__(self):
        self.threads = []

    async def submit(self, task):
        def execute():
            self.threads.append(threading.get_ident())
            return task.execute()
        return await asyncio.to_thread(execute)

    async def aclose(self):
        pass


async def projected_checks():
    # Use the original raw buffers, category worker and projection. Upstream
    # and raw branches retain their own transport rounds even for empty output.
    for upstream_enabled in (False, True):
        for selected in (frozenset({UserCategory}), frozenset()):
            reads = []
            runtime = PreparationRuntime(Renderer(), max_entries=4)

            async def load(*, before=None, after=None, through=None):
                reads.append((before, after, through))
                first, last = ((before.offset - 10, before.offset) if before
                               else (after.offset, after.offset + 10))
                return TranscriptPage(
                    (UserTranscript(f"user {first}"), AssistantTranscript(f"agent {first}")),
                    cursor(first), cursor(last), first > 0, last < 1000,
                )

            boundary_page = page(700, 710)
            boundary = PreparedTranscriptPage(
                boundary_page, transcript_fragments(boundary_page.events), 100,
            )
            upstream = TranscriptPageBuffer(load, cursor(700), runtime) if upstream_enabled else None
            source = ProjectedTranscriptSource(boundary, load, runtime, CategoryProjection(selected), upstream)
            try:
                warmed = [prepared async for prepared in source.prefetch(
                    cursor(500), cursor(510), lambda: True, rounds=8,
                )]
                assert len(reads) == len(warmed) == 8
                assert sorted((p.page.before.offset, p.page.after.offset) for p in warmed) == [
                    (460, 470), (470, 480), (480, 490), (490, 500),
                    (510, 520), (520, 530), (530, 540), (540, 550),
                ]
                for prepared in warmed:
                    assert len(prepared.page.events) == 2 and prepared.retained_bytes > 0
                    events = tuple(event for fragment in prepared.fragments for event in fragment.events)
                    assert events == ((prepared.page.events[0],) if selected else ())
                assert len(runtime._ready) <= runtime.max_entries
            finally:
                source.close()
                if upstream is not None:
                    upstream.close()
                await runtime.aclose()

        # Revoke the existing source/demand during the real async projection,
        # after raw read completion; neither branch may publish its late result.
        for revoke_source in (False, True):
            runtime = PreparationRuntime(Renderer())
            boundary_page = page(700, 710)
            boundary = PreparedTranscriptPage(boundary_page, transcript_fragments(boundary_page.events), 100)
            upstream = TranscriptPageBuffer(load, cursor(700), runtime) if upstream_enabled else None
            source = ProjectedTranscriptSource(
                boundary, load, runtime, CategoryProjection(frozenset({UserCategory})), upstream,
            )
            entered, release, revoked = asyncio.Event(), asyncio.Event(), asyncio.Event()
            original_project = CategoryProjection.project

            async def held_project(projection, prepared, preparation):
                entered.set()
                await release.wait()
                return await original_project(projection, prepared, preparation)

            CategoryProjection.project = held_project
            iterator = source.prefetch(cursor(500), None, lambda: not revoked.is_set())
            pending = asyncio.create_task(anext(iterator))
            try:
                async with asyncio.timeout(10):
                    await entered.wait()
                    if revoke_source:
                        source.close()
                    else:
                        revoked.set()
                    release.set()
                    try:
                        await pending
                    except asyncio.CancelledError:
                        assert revoke_source
                    except StopAsyncIteration:
                        assert not revoke_source
                    else:
                        raise AssertionError("Revoked projection published a late speculative page")
            finally:
                release.set()
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
                await iterator.aclose()
                CategoryProjection.project = original_project
                source.close()
                if upstream is not None:
                    upstream.close()
                await runtime.aclose()


async def projected_app_checks(app, pilot, history):
    """Observe the actual filtered pager's existing lookahead/body worker."""
    from toad.widgets.transcript_fragments import TranscriptBodyPreparation
    from toad.widgets.message_filter import keep_events
    from transcript_history_pilot import until

    view = app.selected_session.conversation
    selected = frozenset({AgentCategory})
    pages, incoming_ids, warmed = [], set(), []
    original_prefetch = ProjectedTranscriptSource.prefetch
    original_prepare = TranscriptBodyPreparation.prepare_fragments

    async def observed_prefetch(source, *args, **kwargs):
        async for prepared in original_prefetch(source, *args, **kwargs):
            pages.append((source, prepared))
            incoming_ids.update(id(fragment) for fragment in prepared.fragments)
            yield prepared

    async def observed_prepare(preparation, fragments, current, *, batch_size):
        incoming_events = {id(event) for fragment in fragments if id(fragment) in incoming_ids
                           for event in fragment.events}
        original_dispatch = preparation.dispatch

        async def observed_dispatch(event):
            result = await original_dispatch(event)
            if id(event) in incoming_events:
                warmed.append(event)
            return result

        # This instance belongs to the original lookahead worker. A revoked
        # prepare_fragments call never dispatches and earns no completion credit.
        with patch.object(preparation, "dispatch", observed_dispatch):
            await original_prepare(preparation, fragments, current, batch_size=batch_size)

    with patch.object(ProjectedTranscriptSource, "prefetch", observed_prefetch), patch.object(
        TranscriptBodyPreparation, "prepare_fragments", observed_prepare,
    ):
        view.visible_categories = selected
        history.filter.request_force()
        history.filter.start_scan()
        await until(lambda: history.filter.overlay is not None
                    and history.filter.overlay.fragment_count
                    and history.filter.overlay.state.accepts_source_work)
        window = view.window
        window.release_anchor()
        window.focus(scroll_visible=False)
        await pilot.pause()
        assert app.screen.focused is window
        await pilot.press("pageup")
        await until(lambda: bool(warmed))

    assert pages and warmed
    assert all(source.projection.selected == selected for source, _ in pages)
    assert all(keep_events(fragment.events, selected)
               for _, prepared in pages for fragment in prepared.fragments)
    assert all(keep_events((event,), selected) for event in warmed)
    assert any(not keep_events((event,), selected)
               for _, prepared in pages for event in prepared.page.events)
    assert app.preparation.retained_bytes <= app.preparation.max_bytes
    assert len(app.preparation._ready) <= app.preparation.max_entries
    assert app._exception is None
    view.visible_categories = all_categories()
    await until(lambda: history.filter.overlay is None
                and all(source.closed for source, _ in pages))
    return {"actual_projected_pages": len(pages), "completed_incoming_body_dispatches": len(warmed),
            "projected_only_bodies": True, "raw_source_events_preserved": True,
            "selected_source_retirement": True, "runtime_resource_bounds": True,
            "provider_inputs": 0, "nativeSDK_inputs": 0}


async def model_checks():
    reads = []
    renderer = Renderer()
    runtime = PreparationRuntime(renderer, max_entries=16)

    async def load(*, before=None, after=None, through=None):
        reads.append((before, after, through))
        return page(before.offset - 10, before.offset) if before else page(after.offset, after.offset + 10)

    buffer = TranscriptPageBuffer(load, cursor(1000), runtime)
    async for _ in buffer.prefetch(cursor(500), cursor(510), lambda: True, rounds=8):
        pass
    assert len(reads) == 16 and len(runtime._ready) == 16
    assert all(identity != threading.get_ident() for identity in renderer.threads)
    expected = await buffer.get(PageRequest(before=cursor(500)))
    assert expected.page.before == cursor(490) and len(reads) == 16
    async for _ in buffer.prefetch(cursor(400), cursor(610), lambda: True, rounds=8):
        pass
    assert len(runtime._ready) <= runtime.max_entries and runtime.retained_bytes <= runtime.max_bytes

    # Two consumers share a blocked read. Cancellation keeps the underlying
    # reader alive and its result available for the remaining consumer.
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def delayed(**kwargs):
        nonlocal calls
        calls += 1
        entered.set()
        await release.wait()
        return page(100, 110)

    shared = TranscriptPageBuffer(delayed, cursor(1000), runtime)
    request = PageRequest(before=cursor(110))
    first = asyncio.create_task(shared.get(request))
    await entered.wait()
    second = asyncio.create_task(shared.get(request))
    first.cancel()
    try:
        await first
    except asyncio.CancelledError:
        pass
    assert calls == 1 and len(runtime._pending) == 1
    release.set()
    assert (await second).page.before == cursor(100) and calls == 1
    shared.close()
    assert all(key.scope is not shared.scope for key in runtime._ready)

    # A retiring view drains already-running IO but never retains late results.
    entered.clear()
    release.clear()
    retired = TranscriptPageBuffer(delayed, cursor(1000), runtime)
    waiter = asyncio.create_task(retired.get(request))
    await entered.wait()
    retired.close()
    release.set()
    try:
        await waiter
    except asyncio.CancelledError:
        pass
    assert all(key.scope is not retired.scope for key in runtime._ready) and not runtime._pending

    # Oversized nested tool inputs also count toward the cache's memory budget.
    async def huge(**kwargs):
        event = ToolStartTranscript(tool_call_id='large', tool_name='read', raw_input={'payload': 'x' * 10000})
        return TranscriptPage((event,), cursor(100), cursor(110), True, True)

    small_runtime = PreparationRuntime(renderer, max_bytes=1024)
    bounded = TranscriptPageBuffer(huge, cursor(1000), small_runtime)
    result = await bounded.get(request)
    assert result.retained_bytes > small_runtime.max_bytes and not small_runtime._ready
    await small_runtime.aclose()

    failures = 0

    async def duplicate(**kwargs):
        nonlocal failures
        failures += 1
        return page(110, 110)

    broken = TranscriptPageBuffer(duplicate, cursor(1000), runtime)
    for _ in range(5):
        async for _ in broken.prefetch(cursor(110), None, lambda: True):
            pass
    assert failures == 1, "Speculative no-progress reads must not loop"
    try:
        await broken.get(request)
    except ValueError:
        pass
    else:
        raise AssertionError("Foreground no-progress read must report its error")
    assert failures == 2
    await runtime.aclose()
    await projected_checks()


async def main():
    import transcript_history_pilot

    if "--projected-only" in sys.argv:
        import importlib.metadata as metadata
        import toad
        package = Path(metadata.distribution("batrachian-toad").locate_file("toad")).resolve()
        assert Path(toad.__file__).resolve().parent == package
        assert package.is_relative_to(Path(sys.prefix).resolve()), "Source overlay is not installed proof"
        await projected_checks()
        await transcript_history_pilot.main(projected_only=True, output=Path(sys.argv[-1]))
        return

    await model_checks()
    await transcript_history_pilot.main()
    print("transcript lookahead: worker preparation, 16-page/byte bounds, shared reads, cancellation, stale retirement, no-progress and data-only warming OK")


if __name__ == "__main__":
    asyncio.run(main())
