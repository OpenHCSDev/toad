"""Original saved bodies reuse Textual's bounded scene on sibling reflows.

This is a source/resource experiment, not installed or physical acceptance.
"""
import asyncio
from collections import Counter
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from time import perf_counter

from agent_comms.comms import Comms
from agent_comms.threads import Thread
from textual._compositor import Compositor
from toad.app import ToadApp
from toad.widgets.transcript_history import TranscriptHistory


async def main():
    evidence = Path(os.environ['FRAGMENT_GEOMETRY_EVIDENCE']).resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='saved-fragment-geometry-', dir=evidence) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / 'wire'),
                          XDG_CONFIG_HOME=str(root / 'config'),
                          XDG_STATE_HOME=str(root / 'state'),
                          XDG_DATA_HOME=str(root / 'data'))
        service = Comms(root / 'wire')
        service.messaging.initialize_private_initial_protocol()
        journal = root / 'saved.jsonl'
        journal.write_text(''.join(json.dumps({'type': 'message', 'message': {
            'role': 'assistant', 'content': f'Original saved fragment {i}.\n\nNative retained geometry.'
        }}) + '\n' for i in range(4)))
        service.registry.declare(Thread('saved', frozenset(), str(root), session_file=str(journal)))
        page = service.transcripts.thread_transcript_page('saved')
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(110, 35)) as pilot:
            await app.selected_session.wait_content_ready()
            view = app.selected_session.conversation
            window = view.window
            history = TranscriptHistory(page)
            await view.contents.mount(history)
            viewport = window.document_viewport

            async def settle():
                async with asyncio.timeout(10):
                    while (viewport._pending or viewport._running
                           or not viewport.visible_bodies_ready):
                        await pilot.pause(.02)
                await pilot.pause(.05)

            await settle()
            await viewport.suspend_source()
            window.release_anchor()
            window.scroll_to(y=0, animate=False, immediate=True)
            await pilot.pause()
            bodies = history.fragment_views
            assert len(bodies) == 4 and all(body.body_ready for body in bodies)
            scene = app.screen._compositor

            def compare():
                actual = scene._arrange_root(app.screen, app.size, visible_only=False)
                reference = Compositor(max_subtree_geometry_entries=0)._arrange_root(
                    app.screen, app.size, visible_only=False)
                assert actual == reference, 'Retained fragment changed native scene geometry'
                assert len(scene._subtree_geometry) <= scene.max_subtree_geometry_entries
                return actual

            compare()
            observed = Counter()
            body_ids = {id(body) for body in bodies}

            def trace(frame, event, arg):
                if (event == 'call' and frame.f_code.co_name == 'arrange_widget'
                        and id(frame.f_locals['widget']) in body_ids):
                    observed['fragment_arrangements'] += 1

            # An unrelated page/sibling invalidates the outer Window. These
            # unchanged fragment resources still have the same native geometry.
            started = perf_counter()
            sys.setprofile(trace)
            try:
                for _ in range(100):
                    history.refresh(layout=True)
                    scene._arrange_root(app.screen, app.size, visible_only=False)
            finally:
                sys.setprofile(None)
            receipt = dict(fragment_arrangements=observed['fragment_arrangements'],
                           profiled_100_reflows_seconds=perf_counter() - started,
                           fragments=len(bodies), native_cache_capacity=scene.max_subtree_geometry_entries,
                           provider_calls=0,
                           boundary='actual saved source/Toad widgets/native compositor, source only')
            (evidence / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
            print(json.dumps(receipt), flush=True)
            assert not observed['fragment_arrangements'], receipt
            compare()
            body = bodies[0]
            await body.update_fragment(replace(body.fragment, events=(replace(
                body.fragment.events[0], text='Changed native source.\n\nFresh extent.\n\nMore rows.'),)))
            await pilot.pause()
            compare()
            assert 'Changed native source' in '\n'.join(
                strip.text for strip in scene.render_strips())
            receipt['source_update_painted'] = True
            body.styles.padding = (1, 2)
            await pilot.pause()
            compare()
            receipt['style_invalidated'] = True
            await pilot.resize_terminal(85, 30)
            await pilot.pause()
            compare()
            receipt['resize_invalidated'] = True
            old_children = set(body.walk_children())
            assert await body.retire_body()
            await pilot.pause()
            retired_scene, _ = compare()
            assert not old_children & retired_scene.keys()
            await body.restore_body()
            await pilot.pause()
            compare()
            assert body.body_ready and not old_children & set(body.walk_children())
            receipt['retirement_and_restore_invalidated'] = True
            await history.remove()
            await pilot.pause()
            final_scene, _ = compare()
            assert not set(bodies) & final_scene.keys()
            assert not set(bodies) & scene._subtree_geometry.keys()
            assert app._exception is None
            receipt['final_disposal_releases_scene'] = True
            (evidence / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
            print(json.dumps(receipt), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
