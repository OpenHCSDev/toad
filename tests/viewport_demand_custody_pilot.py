"""Observe reversal across an original native body's asynchronous restoration.

The app, Markdown bodies, viewport worker and keyboard route are real. The
observer holds one original restoration at its await boundary and records the
existing demand identity handed to its existing acceptance mechanism.
"""

import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from agent_comms.comms import Comms
from textual import events
from toad.app import ToadApp
from toad.widgets.agent_response import AgentResponse


async def main():
    evidence = Path(os.environ['DEMAND_EVIDENCE'])
    evidence.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='native-demand-', dir=evidence) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / 'wire'),
                          XDG_CONFIG_HOME=str(root / 'config'),
                          XDG_STATE_HOME=str(root / 'state'),
                          XDG_DATA_HOME=str(root / 'data'))
        Comms(root / 'wire').messaging.initialize_private_initial_protocol()
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(100, 35)) as pilot:
            await app.selected_session.wait_content_ready()
            view = app.selected_session.conversation
            window, manager = view.window, view.window.document_viewport
            manager.budget = replace(manager.budget, minimum_widgets=10000)
            bodies = [AgentResponse(f'## Native body {i}\n\n' + '\n\n'.join(
                f'Actual paragraph {j} retained by its original Markdown owner.'
                for j in range(8)), paginate=False) for i in range(12)]
            await view.contents.mount(*bodies)
            async with asyncio.timeout(20):
                while manager._running or any(not body.body_ready for body in bodies):
                    await pilot.pause(.02)
            await manager.suspend_source()
            window.focus(scroll_visible=False)
            window.scroll_to(y=window.max_scroll_y / 2, animate=False, immediate=True)
            await pilot.pause(.1)
            visible = window.screen._compositor.visible_widgets
            required = next(body for body in manager.body_roots() if body in visible)
            assert await required.retire_body(), 'Original visible body did not retire'
            await pilot.pause(.1)
            entered, release = asyncio.Event(), asyncio.Event()
            restoration = manager._restore_bodies
            accepts = manager.lookahead.accepts
            observations = []
            original_demand = None

            async def held_restoration(owners, anchor, demand):
                await restoration(owners, anchor, demand)
                if not entered.is_set():
                    entered.set()
                    await release.wait()

            def observe_acceptance(demand):
                accepted = accepts(demand)
                if original_demand is not None:
                    observations.append(dict(original_demand=demand is original_demand,
                                             original_still_current=original_demand is manager.lookahead.demand,
                                             accepted=accepted))
                return accepted

            manager._restore_bodies = held_restoration
            manager.lookahead.accepts = observe_acceptance
            try:
                # The resumed viewport observes native travel at the scroll
                # boundary; request() no longer samples parked geometry.
                manager.resume_source()
                window.scroll_relative(y=1, animate=False, immediate=True)
                await asyncio.wait_for(entered.wait(), 10)
                original_demand = manager.lookahead.demand
                assert original_demand.rows(1) > 0, 'Initial native travel was not forward'
                window.focus(scroll_visible=False)
                assert app.screen.focused is window, 'Native history window lacks keyboard focus'
                key = events.Key('pageup', None)
                key.set_sender(app)
                app._driver.send_message(key)
                async with asyncio.timeout(10):
                    while manager.lookahead.demand.rows(1) >= 0:
                        await asyncio.sleep(.01)
                assert manager.lookahead.demand.rows(1) < 0, 'Native PageUp did not reverse demand'
                release.set()
                async with asyncio.timeout(10):
                    while not observations:
                        await asyncio.sleep(.01)
                receipt = dict(observations=observations,
                               original_native_body=type(required).__name__,
                               native_pageup=True, provider_inputs=0,
                               scope='native source counter; not physical installed acceptance')
                (evidence / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
                print(json.dumps(receipt), flush=True)
                first = observations[0]
                assert first['original_demand'] and not first['original_still_current']
                assert not first['accepted'], 'Reversal admitted the outgoing preparation batch'
            finally:
                release.set()
                manager._restore_bodies = restoration
                manager.lookahead.accepts = accepts
            assert app._exception is None


if __name__ == '__main__':
    asyncio.run(main())
