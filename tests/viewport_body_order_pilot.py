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

from agent_comms.comms import Comms
from toad.app import ToadApp
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
            receipt.update(native_reorder=True, removed_body_released=True,
                           fast_reverse_end=True, resize=True)
            (evidence / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
            print(json.dumps(receipt))


if __name__ == '__main__':
    asyncio.run(main())
