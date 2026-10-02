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
        from agent_comms.transcripts import TranscriptCursor, TranscriptPage
        from agent_comms.transcript_events import AssistantTranscript
        page = TranscriptPage(tuple(AssistantTranscript(
            f"Original saved fragment {i}.\n\nNative retained geometry.") for i in range(4)),
            TranscriptCursor("body-resource", 0), TranscriptCursor("body-resource", 4), False, False)
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(110, 35)) as pilot:
            await app.selected_session.wait_content_ready()
            from toad.widgets.history_anchor import HistoryWindow
            from toad.widgets.prepared_markdown import PreparedConversationMarkdown
            from toad.widgets.streaming_markdown import StreamingMarkdown
            window = HistoryWindow()
            window.styles.width = "100%"
            window.styles.height = 20
            window.styles.position = "absolute"
            await app.selected_session.conversation.mount(window)
            history = TranscriptHistory(page)
            await window.mount(history)
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
            assert len(bodies) == 4 and all(body.body_ready for body in bodies), [(type(body).__name__, body.body_ready, type(body._body_measurement).__name__, body.is_mounted, body.size, [type(child).__name__ for child in body.children]) for body in bodies]
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
            # The original body family paints full retained rows on reentry.
            # A restoration may not parse/remount at the same width.
            family = [body, PreparedConversationMarkdown("# Native prepared body\n\nRetained full lines."),
                      StreamingMarkdown("# Native streaming body\n\nRetained full lines.", paginate=False)]
            await window.mount(*family[1:])
            await pilot.pause()
            window.release_anchor()
            window.scroll_to(y=window.max_scroll_y, animate=False, immediate=True)
            await pilot.pause()
            window.release_anchor()
            family_receipts = []
            for member in family:
                # Retirement owns complete paint even when optional geometry
                # has been evicted. It must not publish a body-local scene.
                scene._subtree_geometry.clear()
                scene.full_map  # Resolve original scene publication before capture.
                published_scene = scene._full_map, scene._visible_map
                scene.render_subtree_strips(member)
                assert scene._full_map is published_scene[0]
                assert scene._visible_map is published_scene[1]
                if not member.body_dormant:
                    assert await member.retire_body(), (type(member).__name__, member.body_ready)
                    await pilot.pause()
                captured = member._body_measurement.content
                captured_rows = tuple(line.text for line in captured.lines)
                assert any(line.strip() for line in captured_rows)
                children = tuple(member.children)
                restored_calls = Counter()
                identity = id(member)
                def observe_reentry(frame, event, arg):
                    if event == 'call' and id(frame.f_locals.get('self')) == identity:
                        if frame.f_code.co_name in {'update', 'recompose', 'materialize_native_body'}:
                            restored_calls[frame.f_code.co_name] += 1
                started = perf_counter()
                sys.setprofile(observe_reentry)
                try:
                    await member.restore_body()
                finally:
                    sys.setprofile(None)
                rows = member.render_lines(member.outer_size.region)
                assert tuple(line.text for line in rows) == captured_rows
                assert member.body_ready and tuple(member.children) == children
                assert not restored_calls, restored_calls
                family_receipts.append(dict(body=type(member).__name__, rendered_lines=len(rows),
                    nonblank_lines=sum(bool(line.strip()) for line in captured_rows),
                    reentry_ms=(perf_counter()-started)*1000, rebuild_calls=dict(restored_calls)))
            receipt['rendered_family_reentry'] = family_receipts
            print(json.dumps(family_receipts), flush=True)
            # Warm admission retains presentation, not offscreen controls.
            # Exercise the original viewport worker rather than invoking its
            # per-body retirement hook to establish this lifecycle.
            selected = family[0]
            await selected.materialize_body()
            await pilot.pause()
            window.release_anchor()
            window.scroll_to(y=window.max_scroll_y, animate=False, immediate=True)
            await pilot.pause()
            assert selected not in scene.visible_widgets
            viewport.resume_source()
            await settle()
            assert selected.body_dormant and selected.body_ready
            assert selected.retained_paint_bytes > 0
            assert not selected.reconstructible_children()
            assert selected in viewport.admitted_bodies
            receipt['offscreen_warm_admission_keeps_rows_not_controls'] = True
            await viewport.suspend_source()
            # Original native mouse routing materializes controls before target
            # selection. No synthetic click retry or independent mouse owner.
            selected = family[-1]
            window.scroll_to_widget(selected, animate=False, immediate=True)
            await pilot.pause()
            # Pilot.click deliberately bypasses App.on_event; feed the original
            # native driver event boundary to exercise preparation and re-hit.
            from textual.events import MouseDown, MouseUp
            point = selected.region.offset + (1, 1)
            assert app.get_widget_at(*point)[0] is selected
            for event_class in (MouseDown, MouseUp):
                app.post_message(event_class(None, point.x, point.y, 0, 0, 1,
                    False, False, False, screen_x=point.x, screen_y=point.y))
                await pilot.pause()
            await pilot.pause()
            assert not selected.body_dormant and selected.children
            receipt['native_input_materialized_original_body'] = True
            for member in family[1:]:
                await member.remove()
            await pilot.pause()
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
