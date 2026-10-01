"""Trace actual prepared code/body native height cache admission, no provider."""
import asyncio
from fractions import Fraction
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from agent_comms.comms import Comms
from agent_comms.transcript_events import AssistantTranscript
from agent_comms.transcripts import TranscriptCursor, TranscriptPage
from toad.app import ToadApp
from toad.widgets.prepared_markdown import PreparedCodeLabel, PreparedConversationMarkdown
from toad.widgets.transcript_history import TranscriptHistory, TranscriptFragmentView
from textual.geometry import Size
from textual._measurement import box_depends_on_available_height


async def main():
    evidence = Path(os.environ['HEIGHT_CONTRACT_EVIDENCE']).resolve()
    evidence.mkdir(parents=True, exist_ok=False)
    with TemporaryDirectory(dir=evidence) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / 'wire'),
                          XDG_CONFIG_HOME=str(root / 'config'),
                          XDG_STATE_HOME=str(root / 'state'),
                          XDG_DATA_HOME=str(root / 'data'))
        Comms(root / 'wire').messaging.initialize_private_initial_protocol()
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(120, 35)) as pilot:
            await app.selected_session.wait_content_ready()
            view = app.selected_session.conversation
            await view.transcript.suspend()
            cursor = TranscriptCursor('saved-code', 1)
            text = '## Native code body\n\nActual paragraph.\n\n```python\n' + ''.join(
                f'value_{index} = {index}\n' for index in range(12)) + '```\n'
            history = TranscriptHistory(TranscriptPage(
                (AssistantTranscript(text),), cursor, cursor, False, False))
            await view.post(history)
            async with asyncio.timeout(10):
                while not view.window.document_viewport.visible_bodies_ready or not history.query(PreparedCodeLabel):
                    await pilot.pause(.02)
            await pilot.pause()
            label = history.query_one(PreparedCodeLabel)
            fragment = label.query_ancestor(TranscriptFragmentView)
            markdown = label.query_ancestor(PreparedConversationMarkdown)
            view.window.scroll_to_widget(fragment, animate=False, immediate=True)
            async with asyncio.timeout(10):
                while not markdown.body_ready:
                    await pilot.pause(.02)
            await pilot.pause()
            dependencies = [dict(kind=type(node).__name__,
                                 policy=type(node._content_height_dependency).__name__,
                                 dependent=node._box_depends_on_available_height(),
                                 native_hooks=node._native_measurement_layout_hooks,
                                 display=node.display, height=str(node.styles.height),
                                 displayed_children=len(node.displayed_children),
                                 fresh_dependent=box_depends_on_available_height(node),
                                 content_dependent=node._content_height_dependency.box_depends(node),
                                 layout=type(node.layout).__name__,
                                 measurement=str(getattr(node, '_body_measurement', 'leaf')))
                            for node in (fragment, *fragment.walk_children())]
            calls = []
            original_height = fragment.get_content_height
            def height(*args):
                calls.append(args[0].height)
                return original_height(*args)
            fragment.get_content_height = height
            fragment._box_model_cache.clear()
            width = fragment.container_size.width
            started = perf_counter()
            boxes = [fragment._get_box_model(Size(width, available), app.size,
                                            Fraction(width), Fraction(available))
                     for available in range(80, 104)]
            elapsed = perf_counter() - started
            arrangements = []
            original_arrange = markdown.layout.arrange
            def arrange(*args, **kwargs):
                arrangements.append(args[2].height)
                return original_arrange(*args, **kwargs)
            markdown.layout.arrange = arrange
            markdown._arrangement_cache.clear()
            layouts = [markdown.arrange(Size(markdown.size.width, available))
                       for available in range(80, 104)]
            del markdown.layout.arrange
            placements = [tuple((item.widget, item.region) for item in layout.placements)
                          for layout in layouts]
            padding_before = label.styles.padding
            label.styles.padding = (padding_before.top + 1, padding_before.right,
                                    padding_before.bottom + 1, padding_before.left)
            await pilot.pause()
            styled = markdown.arrange(Size(markdown.size.width, 80))
            styled_placements = tuple((item.widget, item.region) for item in styled.placements)
            label.styles.height = '1fr'
            await pilot.pause()
            relative_arrangements = []
            def relative_arrange(*args, **kwargs):
                relative_arrangements.append(args[2].height)
                return original_arrange(*args, **kwargs)
            markdown.layout.arrange = relative_arrange
            markdown._arrangement_cache.clear()
            relative = [markdown.arrange(Size(markdown.size.width, available))
                        for available in range(80, 84)]
            del markdown.layout.arrange
            relative_placements = [tuple((item.widget, item.region) for item in layout.placements)
                                   for layout in relative]
            receipt = dict(dependencies=dependencies, box_calls=len(calls),
                           available_heights=calls, elapsed_seconds=elapsed,
                           all_boxes_equal=all(box == boxes[0] for box in boxes),
                           arrangement_calls=len(arrangements), arrangement_heights=arrangements,
                           all_arrangements_equal=all(item == placements[0] for item in placements),
                           padding_before=tuple(padding_before),
                           padding_after=tuple(label.styles.padding),
                           style_invalidated=styled_placements != placements[0],
                           relative_arrangement_calls=len(relative_arrangements),
                           relative_geometry_changed=relative_placements[0] != relative_placements[-1],
                           label_rows=len(label._code_lines), actual_height=str(boxes[0].height),
                           body_ready=fragment.body_ready, native_widgets=len(fragment.walk_children()),
                           agent_bound=view.agent is not None, provider_calls=0,
                           boundary='actual Toad/Markdown/native mounted body/box resolver; source diagnostic, not physical CPU acceptance')
            (evidence/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
            print(json.dumps(receipt), flush=True)
            assert receipt['all_boxes_equal'], receipt
            assert receipt['all_arrangements_equal'], receipt
            assert receipt['style_invalidated'], receipt
            assert receipt['relative_arrangement_calls'] == 4, receipt
            assert receipt['relative_geometry_changed'], receipt
            assert not receipt['agent_bound'], receipt
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()


if __name__ == '__main__':
    asyncio.run(main())
