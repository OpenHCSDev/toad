"""Actual Toad ToolCall, native geometry and worker preparation continuous path.

No provider, Agent, ACP facade, fake UI or renderer replacement is involved.
The full-map counter observes native execution without replacing its methods.
"""
from __future__ import annotations

import asyncio
from contextlib import nullcontext
import hashlib
import json
import os
from pathlib import Path
import sys
import traceback
from tempfile import TemporaryDirectory
from time import perf_counter, process_time

if os.environ.get('WORKER_SIZE_PHYSICAL') == '1':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from acp.schema import ToolCall as ACPToolCall
from agent_comms.comms import Comms
from toad.acp.status import ToolCallStatus
from toad.app import ToadApp
from toad.widgets.tool_call import ToolCall, ToolContent
from toad.widgets.worker_static import WorkerStatic


async def main():
    output = Path(os.environ['WORKER_SIZE_OUTPUT']).resolve()
    output.mkdir(parents=True, exist_ok=False)
    physical = os.environ.get('WORKER_SIZE_PHYSICAL') == '1'
    directory_owner = (nullcontext(os.environ['WORKER_SIZE_ROOT']) if physical
                       else TemporaryDirectory(dir=output))
    with directory_owner as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / 'wire'),
                          XDG_CONFIG_HOME=str(root / 'config'),
                          XDG_STATE_HOME=str(root / 'state'),
                          XDG_DATA_HOME=str(root / 'data'))
        comms = Comms(root / 'wire')
        if physical:
            from agent_comms.active_route import resolve_comms_route
            assert resolve_comms_route().observe_root() == comms.root
        else:
            comms.messaging.initialize_private_initial_protocol()
        app = ToadApp(project_dir=str(root))
        receipt = {'boundary': 'actual source Toad/ToolCall/Contents/native compositor/worker',
                   'source': str(Path(sys.modules['toad.widgets.worker_static'].__file__).resolve()),
                   'provider_calls': 0}
        async with app.run_test(size=(110, 35), headless=not physical) as pilot:
            await app.selected_session.wait_content_ready()
            view = app.selected_session.conversation
            tools = []
            for index in range(12):
                call = ACPToolCall.model_validate({
                    'toolCallId': f'retained-read-{index}', 'kind': 'read',
                    'title': f'Read retained-{index}.py', 'status': 'completed',
                    'rawInput': {'path': f'retained-{index}.py'},
                    'content': [{'type': 'content', 'content': {'type': 'text',
                        'text': f'NATIVE_TOOL_{index} = 1\n' * 12}}],
                })
                tool = ToolCall(ToolCallStatus.from_acp(call))
                await view.post(tool)
                tool.set_expanded(True)
                tools.append(tool)
            await pilot.pause()
            contents = [tool.query_one(ToolContent) for tool in tools]

            def resource(content):
                measurement = content._body_measurement
                if measurement.paint_ready(content):
                    return measurement.content
                workers = tuple(content.query(WorkerStatic))
                if len(workers) == 1:
                    return workers[0].prepared_content
                return None

            async def ready(cohort=None):
                cohort = contents if cohort is None else cohort
                async with asyncio.timeout(15):
                    while any(resource(content) is None for content in cohort):
                        await pilot.pause(.02)
                await pilot.pause()
                for content in cohort:
                    index = contents.index(content)
                    painted = resource(content)
                    assert painted is not None
                    assert f'NATIVE_TOOL_{index}' in painted.text, (index, painted.text)
                    source = tools[index].output.displayed_parts[0].text
                    assert painted.text.count(f'NATIVE_TOOL_{index}') == source.count(f'NATIVE_TOOL_{index}'), (index, painted.text)
                    assert 'Preparing preview' not in painted.text

            await ready()
            # A retired ToolContent owns actual captured paint, not a live
            # WorkerStatic descendant. Expose each original native body first.
            for tool in tools:
                tool.scroll_visible(animate=False, immediate=True)
                await pilot.pause()
                await ready()
            if physical:
                view.window.jump_to_latest()
                await pilot.pause()
                await ready()
                receipt.update(physical_driver=type(app._driver).__name__,
                               retained_tool_bodies=len(contents), ready=True,
                               source_sha256=hashlib.sha256(
                                   Path(sys.modules['toad.widgets.worker_static'].__file__).read_bytes()).hexdigest())
                (output / 'physical-ready.json').write_text(json.dumps(receipt, indent=2) + '\n')
                while app.is_running:
                    await asyncio.sleep(.05)
                return
            scene = app.screen._compositor
            assert any(content not in scene.visible_widgets for content in contents)
            retained = tuple((content, resource(content)) for content in contents
                             if content._body_measurement.paint_ready(content))
            assert retained, 'The native viewport must exercise actual retirement'
            live = tuple((body, body.prepared_content) for content in contents
                         for body in content.query(WorkerStatic))
            counts = {'full_map': 0, 'preparation_full_map': 0, 'preparation_requests': 0}

            def trace(frame, event, argument):
                if event != 'call':
                    return
                if frame.f_code.co_name == '_request_preparation':
                    counts['preparation_requests'] += 1
                if frame.f_code.co_name == '_arrange_root' and frame.f_locals.get('visible_only') is False:
                    counts['full_map'] += 1
                    ancestor = frame.f_back
                    while ancestor is not None:
                        if ancestor.f_code.co_name == '_request_preparation':
                            counts['preparation_full_map'] += 1
                            break
                        ancestor = ancestor.f_back

            started, cpu_started = perf_counter(), process_time()
            sys.setprofile(trace)
            try:
                # Publish the original layout relation against native lazy maps,
                # then use actual keyboard scrolling through the same scene.
                for _ in range(25):
                    scene.reflow_visible(app.screen, app.size,
                                         retain_geometry=app.screen._layout_geometry_targets())
                    app.screen.screen_layout_refresh_signal.publish(app.screen)
                view.window.focus()
                await pilot.press(*(['pageup'] * 8 + ['pagedown'] * 8 + ['pageup'] * 4))
                await pilot.pause()
            finally:
                sys.setprofile(None)
            receipt.update(counts, elapsed_seconds=perf_counter() - started,
                           ui_cpu_seconds=process_time() - cpu_started,
                           retained_tool_bodies=len(contents),
                           retained_paint_resources_reused=all(
                               resource(content) is paint for content, paint in retained),
                           initially_live_workers=len(live),
                           live_workers_reused=(all(body.prepared_content is paint
                                                   for body, paint in live if body.is_attached)
                                                if live else None),
                           initially_retired_bodies=len(retained))
            (output / 'layout-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
            assert counts['preparation_full_map'] == 0, receipt
            await ready()
            assert receipt['retained_paint_resources_reused'], receipt
            assert receipt['live_workers_reused'] is not False, receipt

            await pilot.resize_terminal(85, 30)
            view.window.jump_to_latest()
            await pilot.pause()
            exposed = [content for content in contents if content in scene.visible_widgets]
            assert exposed
            await ready(exposed)
            content = exposed[-1]
            # Real native interaction reacquires controls from retained paint.
            content.scroll_visible(animate=False, immediate=True)
            await pilot.pause()
            await pilot.click(content, offset=(1, 1))
            await ready()
            body = content.query_one(WorkerStatic)
            assert body._ready_request.task.presentation.options.max_width == body.size.width
            body.styles.padding = (0, 2)
            body.styles.color = 'red'
            await pilot.pause()
            await ready()
            assert body._ready_request.task.presentation.options.max_width == body.size.width
            assert body._ready_request.task.presentation.base_style == body.visual_style.rich_style
            index = contents.index(content)
            changed = tools[index].tool_call.call.model_copy(deep=True)
            changed_line = f'NATIVE_TOOL_{index} = "CHANGED"'
            changed.content[0].content.text = (changed_line + '\n') * 12
            await tools[index].update_tool_call(ToolCallStatus.from_acp(changed))
            content.scroll_visible(animate=False, immediate=True)
            await ready()
            assert body._closed and body.prepared_content is None
            body = content.query_one(WorkerStatic)
            visible_text = '\n'.join(strip.text for strip in scene.render_strips())
            source_state = {
                'worker_text': body.prepared_content.text if body.prepared_content else None,
                'body_text': resource(content).text if resource(content) else None,
                'body_state': type(content._body_measurement).__name__,
                'content_region': str(content.region), 'worker_region': str(body.region),
                'window_region': str(view.window.scrollable_content_region),
                'visible_text': visible_text,
            }
            (output / 'source-publication.json').write_text(json.dumps(source_state, indent=2) + '\n')
            assert changed_line in visible_text, source_state
            auto = body
            auto.styles.width = 'auto'
            await pilot.pause()
            await ready()
            assert auto._ready_request.task.presentation.auto_width
            assert auto._ready_request.task.presentation.options.max_width == auto.parent.scrollable_content_region.width
            await pilot.resize_terminal(100, 30)
            # A width change invalidates offscreen retained paint. The native
            # viewport restores its visible/protected cohort, not all history.
            await ready([content for content in contents if content in scene.visible_widgets])
            assert auto._ready_request.task.presentation.options.max_width == auto.parent.scrollable_content_region.width
            receipt.update(resize_reveal=True, padding_and_style=True, source_painted=True,
                           auto_parent_bound=True)
            await tools[index].remove()
            await pilot.pause()
            assert body._closed and body._prepared is None
            receipt['native_disposal'] = True
            (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
            print(json.dumps(receipt), flush=True)
        assert app._exception is None


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except BaseException:
        output = Path(os.environ['WORKER_SIZE_OUTPUT'])
        output.mkdir(parents=True, exist_ok=True)
        (output / 'failure.txt').write_text(traceback.format_exc())
        raise
