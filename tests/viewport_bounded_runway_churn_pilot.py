"""Actual native runway settles when its measured body budget is exhausted."""
import asyncio
from collections import Counter
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from agent_comms.comms import Comms
from toad.app import ToadApp
from toad.widgets.agent_response import AgentResponse


async def main():
    evidence = Path(os.environ['CHURN_EVIDENCE'])
    evidence.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='bounded-runway-', dir=evidence) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / 'wire'),
                          XDG_CONFIG_HOME=str(root / 'config'),
                          XDG_STATE_HOME=str(root / 'state'),
                          XDG_DATA_HOME=str(root / 'data'))
        Comms(root / 'wire').messaging.initialize_private_initial_protocol()
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(110, 35)) as pilot:
            await app.selected_session.wait_content_ready()
            view = app.selected_session.conversation
            window = view.window
            viewport = window.document_viewport
            viewport.budget = replace(viewport.budget, minimum_widgets=60, widgets_per_row=0)
            docs = [AgentResponse(f'## Bounded native body {i}\n\n' + '\n\n'.join(
                f'Paragraph {j}: original native Markdown geometry and paint.'
                for j in range(4)), paginate=False) for i in range(32)]
            await view.contents.mount(*docs)
            await pilot.pause(.5)
            window.focus(scroll_visible=False)
            await pilot.press('pageup', 'pageup', 'pageup', 'pageup')
            await pilot.pause(.5)
            before = viewport.body_evictions
            observed = Counter()

            def trace(frame, event, arg):
                if event == 'call' and frame.f_code.co_name in ('restore_body', 'retire_body', '_reconcile'):
                    observed[frame.f_code.co_name] += 1

            sys.setprofile(trace)
            try:
                # No further key, source, size or style changes in this interval.
                await pilot.pause(.8)
            finally:
                sys.setprofile(None)
            result = {'stationary_calls': dict(observed),
                      'stationary_evictions': viewport.body_evictions - before,
                      'reconciling': viewport._worker is not None, 'pending': viewport._pending,
                      'visible_ready': viewport.visible_bodies_ready,
                      'warm_widgets': sum(1 + len(body.walk_children())
                                          for key in viewport._warm.values()
                                          if (body := key()) is not None),
                      'widget_limit': viewport.budget.widget_limit(window.size.height)}
            (evidence / 'receipt.json').write_text(json.dumps(result, indent=2) + '\n')
            print(json.dumps(result), flush=True)
            assert viewport._worker is None and not viewport._pending, result
            assert result['stationary_evictions'] == 0, result
            assert result['visible_ready']
            assert result['warm_widgets'] <= result['widget_limit']
            cold = next(body for body in docs if body.body_dormant)
            old_cost = cold.retained_widget_count
            assert old_cost > 1, 'Dormant resource lost its materialized cost'
            await cold.update('## Changed resource\n\n' + '\n\n'.join(
                f'Changed paragraph {i} must publish fresh native children.' for i in range(8)))
            window.release_anchor()
            window.scroll_to_widget(cold, animate=False, immediate=True)
            await pilot.pause(.5)
            assert cold.body_ready and cold.retained_widget_count > old_cost
            result['content_cost_invalidated'] = True
            await pilot.resize_terminal(85, 35)
            await pilot.pause(.5)
            assert viewport.visible_bodies_ready
            result['resize_preserves_visible_source'] = True
            assert viewport._worker is None and not viewport._pending
            assert app._exception is None
            (evidence / 'receipt.json').write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    asyncio.run(main())
