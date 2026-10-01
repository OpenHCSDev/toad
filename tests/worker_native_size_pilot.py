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
from toad.widgets.tool_call import ToolCall
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
            async with asyncio.timeout(15):
                while any(not tool.query(WorkerStatic) for tool in tools):
                    await pilot.pause(.02)
            bodies = [tool.query_one(WorkerStatic) for tool in tools]

            async def ready():
                async with asyncio.timeout(15):
                    await asyncio.gather(*(body.wait_ready() for body in bodies if body.is_attached))
                await pilot.pause()

            await ready()
            # A retained resource is warm only after its actual native geometry
            # has been exposed. Initial offscreen mount may still use its
            # provisional width; first exposure legitimately changes wrapping.
            for tool in tools:
                tool.scroll_visible(animate=False, immediate=True)
                await pilot.pause()
                await ready()
            if physical:
                view.window.jump_to_latest()
                await pilot.pause()
                await ready()
                receipt.update(physical_driver=type(app._driver).__name__,
                               retained_tool_bodies=len(bodies), ready=True,
                               source_sha256=hashlib.sha256(
                                   Path(sys.modules['toad.widgets.worker_static'].__file__).read_bytes()).hexdigest())
                (output / 'physical-ready.json').write_text(json.dumps(receipt, indent=2) + '\n')
                while app.is_running:
                    await asyncio.sleep(.05)
                return
            scene = app.screen._compositor
            assert any(body not in scene.visible_widgets for body in bodies)
            prepared = tuple(body._prepared for body in bodies)
            widths = tuple(body._ready_request.task.presentation.options.max_width for body in bodies)
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
                    scene.reflow_visible(app.screen, app.size)
                    app.screen.screen_layout_refresh_signal.publish(app.screen)
                view.window.focus()
                await pilot.press(*(['pageup'] * 8 + ['pagedown'] * 8 + ['pageup'] * 4))
                await pilot.pause()
            finally:
                sys.setprofile(None)
            receipt.update(counts, elapsed_seconds=perf_counter() - started,
                           ui_cpu_seconds=process_time() - cpu_started,
                           retained_tool_bodies=len(bodies),
                           prepared_resources_reused=all(a is b._prepared for a, b in zip(prepared, bodies)),
                           initial_prepared_widths=widths,
                           final_prepared_widths=tuple(body._ready_request.task.presentation.options.max_width
                                                       for body in bodies))
            (output / 'layout-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
            assert counts['preparation_full_map'] == 0, receipt
            assert receipt['prepared_resources_reused'], receipt

            await pilot.resize_terminal(85, 30)
            view.window.jump_to_latest()
            await pilot.pause()
            await ready()
            exposed = [body for body in bodies if body in scene.visible_widgets]
            assert exposed
            assert all(body._ready_request.task.presentation.options.max_width == body.size.width
                       for body in exposed)
            body = exposed[-1]
            body.styles.padding = (0, 2)
            body.styles.color = 'red'
            await pilot.pause()
            await ready()
            assert body._ready_request.task.presentation.options.max_width == body.size.width
            assert body._ready_request.task.presentation.base_style == body.visual_style.rich_style
            body.set_source('CHANGED_NATIVE_TOOL_SOURCE')
            await ready()
            assert 'CHANGED_NATIVE_TOOL_SOURCE' in '\n'.join(strip.text for strip in scene.render_strips())
            auto = exposed[0]
            auto.styles.width = 'auto'
            await pilot.pause()
            await ready()
            assert auto._ready_request.task.presentation.auto_width
            assert auto._ready_request.task.presentation.options.max_width == auto.parent.scrollable_content_region.width
            await pilot.resize_terminal(100, 30)
            await ready()
            assert auto._ready_request.task.presentation.options.max_width == auto.parent.scrollable_content_region.width
            receipt.update(resize_reveal=True, padding_and_style=True, source_painted=True,
                           auto_parent_bound=True)
            await tools[-1].remove()
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
