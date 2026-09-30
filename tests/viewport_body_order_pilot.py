"""Actual native body admission keeps document order without expanding bodies.

Profile only the owner-selection seam, then exercise real scrolling and changed
native custody. Headless source/resource proof, not physical paint acceptance.
"""
import asyncio
import cProfile
from dataclasses import replace
import json
import os
from pathlib import Path
import pstats
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch

from agent_comms.comms import Comms
from agent_comms.threads import Thread
from toad.app import ToadApp
from toad.acp.agent import Agent
from toad.agent_schema import AgentDefinition
from toad.widgets.transcript_history import TranscriptHistory, TranscriptFragmentView
from toad.widgets.agent_response import AgentResponse
from textual.widget import Widget
from textual.widgets import Label
from textual.widgets._markdown import MarkdownBlock


async def main():
    evidence = Path(os.environ['BODY_ORDER_EVIDENCE']).resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='body-order-', dir=evidence) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / 'wire'), XDG_CONFIG_HOME=str(root / 'config'),
                          XDG_STATE_HOME=str(root / 'state'), XDG_DATA_HOME=str(root / 'data'))
        Comms(root / 'wire').messaging.initialize_private_initial_protocol()
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(110, 35)) as pilot:
            await app.selected_session.wait_content_ready()
            view = app.selected_session.conversation
            window, viewport = view.window, view.window.document_viewport
            viewport.budget = replace(viewport.budget, minimum_widgets=10000, widgets_per_row=0)
            docs = [AgentResponse(f'## Resource body {i}\n\n' + '\n\n'.join(
                f'Paragraph {j}: native Markdown retains terminal output and reader order.'
                for j in range(20)), paginate=False) for i in range(24)]
            await view.contents.mount(*docs)

            async def settle():
                async with asyncio.timeout(15):
                    while viewport._pending or viewport._running or not viewport.visible_bodies_ready:
                        await pilot.pause(.02)
                await pilot.pause(.05)

            await settle()
            await viewport.suspend_source()
            assert tuple(viewport.body_roots()) == tuple(docs)
            native_descendants = len(window.walk_children())
            assert native_descendants > 400
            originals = tuple(docs)
            profile = cProfile.Profile()
            profile.enable()
            for _ in range(100):
                assert tuple(viewport.body_roots()) == originals
            profile.disable()
            profile.dump_stats(str(evidence / 'body-order.prof'))
            walks = sum(row[1] for (_, _, name), row in pstats.Stats(profile).stats.items()
                        if name == 'walk_children')
            timings = {}
            # Same materialized native trees and original WeakSet registrations.
            # Counterfactual is the deleted traversal, not a substitute viewport.
            for label in ('expanded_native_tree', 'registered_body_boundaries'):
                started = perf_counter()
                for _ in range(500):
                    if label == 'expanded_native_tree':
                        owners = tuple(owner for owner in viewport.owners if owner.is_attached
                            and not any(parent in viewport.owners for parent in owner.ancestors))
                        roots = set(owners)
                        sequence = tuple(node for node in window.walk_children() if node in roots)
                    else:
                        sequence = tuple(viewport.body_roots())
                    assert sequence == originals
                timings[label] = (perf_counter() - started) * 1000 / 500
            receipt = dict(native_descendants=native_descendants, body_roots=len(originals),
                profiled_selection_walks=walks, unprofiled_selection_ms=timings)
            # Repeated admission of the same native materialization must reuse
            # the body's measured cost, not expand all its rendered descendants.
            native_costs = tuple(1 + len(body.walk_children()) for body in docs)
            assert tuple(body.retained_widget_count for body in docs) == native_costs
            cost_profile = cProfile.Profile()
            cost_started = perf_counter()
            cost_profile.enable()
            for _ in range(100):
                admitted = viewport.budget.admit(
                    docs, (), window.size.height, app.preparation.max_bytes,
                )
                assert len(admitted) == len(docs)
            cost_profile.disable()
            cost_elapsed = (perf_counter() - cost_started) * 1000 / 100
            cost_profile.dump_stats(str(evidence / 'body-cost.prof'))
            cost_walks = sum(row[1] for (_, _, name), row in pstats.Stats(cost_profile).stats.items()
                             if name == 'walk_children')
            receipt.update(profiled_admission_walks=cost_walks,
                           profiled_admission_ms=cost_elapsed)
            (evidence / 'body-cost.json').write_text(json.dumps(receipt, indent=2) + '\n')
            assert cost_walks == 0, receipt
            # A real source update changes native custody and expires the cost.
            await docs[0].update('## Changed body\n\n' + '\n\n'.join(
                f'Changed paragraph {i}: actual native source reconstruction.' for i in range(30)))
            await settle()
            changed_cost = 1 + len(docs[0].walk_children())
            assert changed_cost != native_costs[0]
            assert docs[0].retained_widget_count == changed_cost
            # Dormancy carries the retired native cost; restoring the original
            # source measures the current native resource rather than reusing a
            # count belonging to its removed descendants.
            retired = docs[10]
            fixed = Label('Native decoration survives Markdown block retirement')
            await retired.mount(fixed)
            await settle()
            retired_cost = retired.retained_widget_count
            removing = next(child for child in retired.children if isinstance(child, MarkdownBlock))
            pruning, release_prune = asyncio.Event(), asyncio.Event()
            original_prune = Widget.on_prune

            async def held_prune(widget, event):
                if widget is removing:
                    pruning.set()
                    await release_prune.wait()
                await original_prune(widget, event)

            with patch.object(Widget, 'on_prune', held_prune):
                retirement = asyncio.create_task(retired.retire_body())
                try:
                    await asyncio.wait_for(pruning.wait(), 5)
                    assert retired.body_dormant and removing in retired.children
                    current = 1 + len(retired.walk_children())
                    assert retired.materialized_widget_count == current > 1
                    assert retired.retained_widget_count == retired_cost
                    (evidence / 'pending-prune-cost.json').write_text(json.dumps(dict(
                        resource=id(retired), native_children=[id(c) for c in retired.children],
                        dormant=retired.body_dormant, restore_reservation=retired_cost,
                        actual_native_cost=current, declared_native_cost=retired.materialized_widget_count,
                    ), indent=2) + '\n')
                finally:
                    release_prune.set()
                    assert await asyncio.wait_for(retirement, 5)
            assert retired.body_dormant and retired.retained_widget_count == retired_cost
            assert fixed in retired.children
            assert retired.materialized_widget_count == 1 + len(retired.walk_children())
            assert retired.materialized_widget_count < retired.retained_widget_count
            await retired.restore_body()
            await settle()
            assert not retired.body_dormant
            assert retired.retained_widget_count == 1 + len(retired.walk_children())
            receipt.update(native_content_cost_invalidated=True,
                           retired_cost_retained=True, restored_cost_current=True,
                           pending_prune_residency_exact=True,
                           retained_nonblock_residency_exact=True)
            viewport.resume_source()
            window.focus(scroll_visible=False)
            await pilot.press('pageup', 'pageup', 'pagedown', 'pageup', 'end')
            await settle()
            assert window.follows_tail and window.scroll_y == window.max_scroll_y
            assert tuple(viewport.body_roots()) == originals
            # Native reorder is custody, not append-only birth order.
            # No second catalog may preserve the old order.
            view.contents.move_child(docs[-1], before=docs[0])
            await settle()
            assert tuple(viewport.body_roots()) == (docs[-1], *docs[:-1])
            await docs[5].remove()
            await settle()
            assert docs[5] not in tuple(viewport.body_roots())
            await pilot.resize_terminal(85, 35)
            await settle()
            assert viewport.visible_bodies_ready
            assert app._exception is None
            # Pause actual fragment Mount after its original registration. The
            # snapshot owns the native window lock while composition is pending;
            # owner order must derive this same tree without a stale catalog.
            service = Comms(root / 'wire')
            journal = root / 'saved.jsonl'
            journal.write_text(''.join(json.dumps({'type': 'message', 'message': {
                'role': 'assistant', 'content': f'Saved custody row {i}. Native pending mount.'
            }}) + '\n' for i in range(6)))
            service.registry.declare(Thread('saved', frozenset(), str(root), session_file=str(journal)))
            agent = Agent(root, AgentDefinition('body-order', 'body-order', {}), None)
            view.set_reactive(type(view).agent, agent)
            entered, release = asyncio.Event(), asyncio.Event()
            mounting = []
            registration_boundary = []
            original_mount = TranscriptFragmentView.on_mount

            async def held_mount(body):
                # Native custody precedes the Mount handler's viewport
                # registration. The original publication fence must exclude
                # this intermediate tree from a reader's accepted source.
                owning_history = body.query_ancestor(TranscriptHistory)
                assert body in owning_history.fragment_views
                assert body not in viewport.owners
                assert window.history_lock.locked() and window.history_mutating()
                assert not view.screen.viewport_presentation.prepare()
                registration_boundary.append(dict(
                    native_child=id(body), parent=id(body.parent),
                    source=id(owning_history), reader_publication_fenced=True,
                ))
                original_mount(body)
                mounting.append(body)
                entered.set()
                await release.wait()

            with patch.object(TranscriptFragmentView, 'on_mount', held_mount):
                task = asyncio.create_task(view.transcript.snapshot(
                    service.transcripts.thread_transcript_page('saved')))
                try:
                    await asyncio.wait_for(entered.wait(), 5)
                    assert window.history_mutating()
                    assert mounting[0] in tuple(viewport.body_roots())
                    assert all(body.parent is not None for body in viewport.body_roots())
                finally:
                    release.set()
                    await asyncio.wait_for(task, 10)
            await settle()
            # Exercise the same boundary on an already accepted source. A
            # real native source update can mount the next tail while the
            # viewport worker itself has no pending job. That is why its
            # settlement is not an accepted-source observation fence.
            history = view.contents.query_children(TranscriptHistory).first()
            with journal.open('a') as target:
                for i in range(6, 12):
                    target.write(json.dumps({'type': 'message', 'message': {
                        'role': 'assistant', 'content': f'New saved custody row {i}.'
                    }}) + '\n')
            changed_page = service.transcripts.thread_transcript_page('saved')
            entered, release = asyncio.Event(), asyncio.Event()
            async def held_registration(body):
                assert body in history.fragment_views and body not in viewport.owners
                assert window.history_lock.locked() and window.history_mutating()
                assert not view.screen.viewport_presentation.prepare()
                entered.set()
                await release.wait()
                original_mount(body)

            with patch.object(TranscriptFragmentView, 'on_mount', held_registration):
                task = asyncio.create_task(history.update_live(changed_page))
                try:
                    await asyncio.wait_for(entered.wait(), 5)
                    assert history.state.reports_coverage
                    raw_roots = tuple(viewport.body_roots())
                    raw_fragments = history.fragment_views
                    assert raw_roots != raw_fragments
                    (evidence / 'pre-admission-custody.json').write_text(json.dumps({
                        'history_lock_held': window.history_lock.locked(),
                        'native_publication_fenced': window.history_mutating(),
                        'raw_roots': [id(body) for body in raw_roots],
                        'raw_fragments': [id(body) for body in raw_fragments],
                        'pending_mount': [id(body) for body in mounting],
                    }, indent=2) + '\n')
                finally:
                    release.set()
                    await asyncio.wait_for(task, 10)
            await settle()
            # Scroll work can start another real page mount after snapshot()
            # completes. Read accepted custody through its original owner,
            # rather than treating viewport-work settlement as source admission.
            async with window.history_lock:
                history = view.contents.query_children(TranscriptHistory).first()
                assert history.state.reports_coverage
                roots, fragments = tuple(viewport.body_roots()), history.fragment_views
                def custody(body):
                    return dict(identity=id(body), kind=type(body).__name__,
                                parent=id(body.parent), attached=body.is_attached,
                                closing=body._closing)
                accepted_custody = {
                    'history_lock_held': window.history_lock.locked(),
                    'source': id(history),
                    'registered_pages': [id(page) for page in history.pages],
                    'roots': [custody(body) for body in roots],
                    'fragments': [custody(body) for body in fragments],
                    'registration_boundary': registration_boundary,
                }
                (evidence / 'accepted-custody.json').write_text(
                    json.dumps(accepted_custody, indent=2) + '\n')
                assert roots == fragments
                exact_native_cost = len(history.walk_children())
                assert history.widget_count == exact_native_cost
                resident_profile = cProfile.Profile()
                resident_profile.enable()
                for _ in range(100):
                    assert history.widget_count == exact_native_cost
                resident_profile.disable()
                resident_profile.dump_stats(str(evidence / 'history-native-cost.prof'))
                resident_walks = sum(value[0] for (_, _, name), value in
                                     pstats.Stats(resident_profile).stats.items() if name == 'walk_children')
                receipt.update(history_native_cost_exact=True,
                               history_native_widgets=exact_native_cost,
                               profiled_resident_walks=resident_walks)
            assert agent.process.process is None and agent.process.runner is None
            assert app._exception is None
            receipt.update(native_reorder=True, removed_body_released=True,
                           fast_reverse_end=True, resize=True, pending_native_mount=True,
                           accepted_canonical_tree=True, pre_registration_frame_fenced=True,
                           raw_custody_mismatch_reproduced=True)
            (evidence / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
            print(json.dumps(receipt))


async def readiness_journey():
    """One real mount/expansion/retirement/restore journey; no provider."""
    from agent_comms.transcript_events import AssistantTranscript
    from agent_comms.transcripts import TranscriptCursor, TranscriptPage
    from toad.widgets.transcript_fragments import TranscriptFragment
    from toad.widgets.transcript_history import TranscriptPageView

    evidence = Path(os.environ['BODY_ORDER_EVIDENCE']).resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    entered, release = asyncio.Event(), asyncio.Event()

    class HeldBody(AgentResponse):
        async def _parse_tokens(self, parser, markdown, *, use_thread):
            entered.set()
            await release.wait()
            return await super()._parse_tokens(parser, markdown, use_thread=use_thread)

    class HeldFragment(TranscriptFragmentView):
        def compose(self):
            yield HeldBody('NATIVE_BODY_READY\n\nOriginal mounted Markdown.', paginate=False)

    with TemporaryDirectory(prefix='body-readiness-', dir=evidence) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / 'wire'), XDG_CONFIG_HOME=str(root / 'config'),
                          XDG_STATE_HOME=str(root / 'state'), XDG_DATA_HOME=str(root / 'data'))
        Comms(root / 'wire').messaging.initialize_private_initial_protocol()
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(110, 35)) as pilot:
            await app.selected_session.wait_content_ready()
            operations = []
            try:
                view = app.selected_session.conversation
                viewport = view.window.document_viewport
                await viewport.suspend_source()
                fragment = HeldFragment(TranscriptFragment((AssistantTranscript('NATIVE_BODY_READY'),)))

                class HeldPage(TranscriptPageView):
                    def _body(self, source):
                        assert source == fragment.fragment
                        return fragment

                cursor = TranscriptCursor('', 0)
                page = TranscriptPage(fragment.fragment.events, cursor, cursor, False, False)
                history = TranscriptHistory(page, fragments=(fragment.fragment,))
                history.pages[0] = HeldPage(page, fragments=(fragment.fragment,))
                mounting = asyncio.ensure_future(view.contents.mount(history))
                operations.append(mounting)
                await asyncio.wait_for(entered.wait(), 5)
                print("HELD_NATIVE_PARSE", flush=True)
                assert not fragment.is_mounted and not fragment.body_ready
                release.set()
                await asyncio.wait_for(mounting, 5)
                await pilot.pause()
                assert fragment.is_mounted and fragment.body_ready

                # Later native composition is independent of the parent's Mount.
                entered.clear()
                release.clear()
                child = HeldBody('LATER_NATIVE_BODY', paginate=False)
                child.styles.min_height = 1
                expanding = asyncio.ensure_future(fragment.mount(child))
                operations.append(expanding)
                await asyncio.wait_for(entered.wait(), 5)
                print("HELD_NATIVE_PARSE", flush=True)
                assert fragment.is_mounted and fragment.body_ready
                assert not child.is_mounted and not child.body_ready
                assert child not in viewport.owners
                assert child not in app.screen._compositor.visible_widgets
                assert not await fragment.retire_body(), 'Pruning abandoned a pending nested Mount'
                release.set()
                await asyncio.wait_for(expanding, 5)
                await pilot.pause()
                assert viewport.visible_bodies_ready
                assert fragment._body_measurement is not None
                # Restore a visible nested resource through its original body
                # owner while the containing fragment remains mounted.
                assert child._body_measurement is not None
                assert await child.retire_body()
                await pilot.pause()
                assert child.is_mounted and not child.body_ready
                assert child not in viewport.owners
                assert child in app.screen._compositor.visible_widgets
                assert not viewport.visible_bodies_ready
                assert not await fragment.retire_body()
                entered.clear()
                release.clear()
                restoring_child = asyncio.create_task(child.restore_body())
                operations.append(restoring_child)
                await asyncio.wait_for(entered.wait(), 5)
                assert fragment.is_mounted and fragment.body_ready
                assert child.is_mounted and not child.body_ready
                assert not viewport.visible_bodies_ready
                assert not await fragment.retire_body()
                release.set()
                await asyncio.wait_for(restoring_child, 5)
                await pilot.pause()
                assert child.body_ready and viewport.visible_bodies_ready

                # Frame admission consumes native visibility, not a subtree census.
                profile = cProfile.Profile()
                profile.enable()
                for _ in range(100):
                    assert viewport.visible_bodies_ready
                profile.disable()
                walks = sum(row[1] for (_, _, name), row in pstats.Stats(profile).stats.items()
                            if name == 'walk_children')
                profile.dump_stats(str(evidence / 'readiness.prof'))
                assert walks == 0

                assert await fragment.retire_body()
                assert not fragment.body_ready and not fragment.children
                entered.clear()
                release.clear()
                restoring = asyncio.create_task(fragment.restore_body())
                operations.append(restoring)
                await asyncio.wait_for(entered.wait(), 5)
                print("HELD_NATIVE_PARSE", flush=True)
                assert fragment.is_mounted and not fragment.body_ready
                release.set()
                await asyncio.wait_for(restoring, 5)
                await pilot.pause()
                assert fragment.body_ready and viewport.visible_bodies_ready
                paint = '\n'.join(strip.text for strip in app.screen._compositor.render_strips())
                assert 'NATIVE_BODY_READY' in paint
                (evidence / 'restored.svg').write_text(app.export_screenshot())
                receipt = dict(initial_native_mount_joined=True, later_pending_mount_not_yet_visible=True,
                               visible_nested_restore_blocks_frame=True,
                               retirement_preserves_pending_nested_mount=True, restored_native_body_painted=True,
                               profiled_frame_subtree_walks=walks, provider_calls=0,
                               boundary='Actual Toad native widgets/Pilot; source scope, not installed physical CPU acceptance')
                (evidence / 'readiness-receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
                assert app._exception is None
                print(json.dumps(receipt))
            finally:
                release.set()
                await asyncio.wait_for(asyncio.gather(*operations, return_exceptions=True), 10)


if __name__ == '__main__':
    import sys
    asyncio.run(readiness_journey() if '--readiness' in sys.argv else main())
