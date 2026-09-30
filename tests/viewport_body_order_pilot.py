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
            original_mount = TranscriptFragmentView.on_mount

            async def held_mount(body):
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
            history = view.contents.query_children(TranscriptHistory).first()
            assert history.state.reports_coverage
            assert tuple(viewport.body_roots()) == history.fragment_views
            assert agent.process.process is None and agent.process.runner is None
            assert app._exception is None
            receipt.update(native_reorder=True, removed_body_released=True,
                           fast_reverse_end=True, resize=True, pending_native_mount=True,
                           accepted_canonical_tree=True)
            (evidence / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
            print(json.dumps(receipt))


if __name__ == '__main__':
    asyncio.run(main())
