"""Actual retained native/ACP reader, original goal-read custody, physical return."""
import asyncio
import json
import os
from pathlib import Path

from compaction_summary_stream_native_installed_pilot import reconnect_cancelled_source
from native_loaded_return_cache_pilot import PaintedReturnApp, click_session
from toad.navigation_target import NavigationContext, channel_target


class ObservedGoalReturnApp(PaintedReturnApp):
    def _display(self, screen, renderable):
        super()._display(screen, renderable)
        if self.expected_source_id is not None:
            self.goal_display_trace.append({
                'rendered': renderable is not None, 'batch': self._batch_count,
                'selected': self.selected_mode, 'expected': self.expected_source_id,
                'current_screen': screen is self.screen,
            })


async def held_original_read(app, pilot, agent, comms):
    source = app.selected_session
    view = source.conversation
    await view.goal_observation.refresh()
    project = agent.project_root_path
    user = comms.messaging.user_identity(str(project)).name
    await channel_target('#team').open(NavigationContext(app, app.selected_mode, project, user))
    await app.selected_session.wait_content_ready()
    observation = view.goal_observation
    original = observation.read
    entered, release = asyncio.Event(), asyncio.Event()

    async def held(agent):
        # Keep the actual RPC result in its original observation read lifetime.
        # No source, goal, protocol packet or view is substituted.
        result = await original(agent)
        entered.set()
        await release.wait()
        return result

    observation.read = held
    app.goal_display_trace = []
    click = asyncio.create_task(click_session(app, pilot, source))
    try:
        async with asyncio.timeout(20):
            await entered.wait()
        # Let the existing compositor complete a frame while that read remains
        # pending. The baseline admission holds both lock and atomic batch.
        async def first_frame():
            while app.first_paint_at is None:
                await asyncio.sleep(.01)
        try:
            async with asyncio.timeout(1):
                await first_frame()
        except TimeoutError:
            pass
        receipt = {'first_paint_before_read_release': app.first_paint_at is not None,
                   'native_admission_lock_held': app.workspace_chrome.native._lock.locked(),
                   'atomic_selection_held': app._atomic_mode_switch,
                   'original_goal_read_pending': not observation.task.done(),
                   'source_agent_unchanged': view.agent is agent,
                   'canonical_busy': agent.current_turn.busy,
                   'no_prompt_or_compaction': True}
        evidence = Path(os.environ['L0A_EVIDENCE'])
        (evidence / 'held-goal-read.json').write_text(json.dumps(receipt, indent=2))
        (evidence / 'held-goal-read.svg').write_text(app.export_screenshot())
    finally:
        release.set()
        try:
            await click
        finally:
            Path(os.environ['L0A_EVIDENCE'], 'display-trace.json').write_text(
                json.dumps(app.goal_display_trace, indent=2))
        await observation.refresh()
        observation.read = original
    assert receipt['first_paint_before_read_release'], receipt
    assert not receipt['native_admission_lock_held'], receipt
    assert not receipt['atomic_selection_held'], receipt
    assert receipt['original_goal_read_pending'] and receipt['source_agent_unchanged']


if __name__ == '__main__':
    asyncio.run(reconnect_cancelled_source(app_type=ObservedGoalReturnApp,
                                         after_cold_load=held_original_read, headless=False))
