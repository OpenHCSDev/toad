"""Actual retained native/ACP reader, original goal-read custody, physical return."""
import asyncio
from functools import wraps
import json
import os
from pathlib import Path
import sys

from toad.navigation_target import NavigationContext, channel_target
from toad.widgets.conversation import Conversation


async def held_original_read(app, pilot, agent, comms):
    from native_loaded_return_cache_pilot import click_session

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
    click = asyncio.create_task(click_session(app, pilot, source))
    try:
        async with asyncio.timeout(20):
            await entered.wait()
        # Let the existing compositor complete a frame while that read remains
        # pending. The original observation read must not withhold the native frame.
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
                   'paint_batch_held': bool(app._batch_count),
                   'original_goal_read_pending': not observation.task.done(),
                   'source_agent_unchanged': view.agent is agent,
                   'canonical_busy': agent.current_turn.busy,
                   'no_prompt_or_compaction': True}
        evidence = Path(os.environ['L0A_EVIDENCE'])
        (evidence / 'held-goal-read.json').write_text(json.dumps(receipt, indent=2))
        (evidence / 'held-goal-read.svg').write_text(app.export_screenshot())
    finally:
        release.set()
        await click
        await observation.refresh()
        observation.read = original
    assert receipt['first_paint_before_read_release'], receipt
    assert not receipt['native_admission_lock_held'], receipt
    assert not receipt['paint_batch_held'], receipt
    assert receipt['original_goal_read_pending'] and receipt['source_agent_unchanged']


async def pending_readiness(app, pilot, comms, project, evidence):
    """Original configured read-only fixture; real readiness, read and teardown."""
    source = app.selected_session
    view = source.conversation
    agent = view.agent
    assert agent is not None and agent.session.connected
    observations = (view.goal_observation, view.delivery_observation)
    await asyncio.gather(*(observation.refresh() for observation in observations))
    entered = [asyncio.Event(), asyncio.Event()]
    release = asyncio.Event()
    ready, resized = asyncio.Event(), asyncio.Event()
    original_reads = [observation.read for observation in observations]
    original_ready, original_resize = Conversation.on_agent_ready, Conversation.on_resize
    captured_tasks = []
    checks = {}
    editor = view.prompt.prompt_text_area
    document, history, text = editor.document, editor.history, editor.text
    size = app.size

    @wraps(original_ready)
    async def observed_ready(recipient, message):
        # Observe the real AgentSession event through its original declaration.
        # This does not publish AgentReady or call the handler on its behalf.
        await original_ready(recipient, message)
        if recipient is view:
            assert message.event.reconnected and recipient.agent is agent
            ready.set()

    @wraps(original_resize)
    def observed_resize(recipient):
        original_resize(recipient)
        if recipient is view:
            resized.set()

    for index, observation in enumerate(observations):
        async def held(current_agent, *, index=index):
            assert current_agent is agent
            result = await original_reads[index](current_agent)
            # The actual RPC has returned. Only delivery of its original result
            # remains pending in the original observation's owned Task.
            entered[index].set()
            await release.wait()
            return result
        observation.read = held
    Conversation.on_agent_ready, Conversation.on_resize = observed_ready, observed_resize
    try:
        await agent.session.reconnect()
        async with asyncio.timeout(20):
            await ready.wait()
            await asyncio.gather(*(event.wait() for event in entered))
        captured_tasks = [observation.task for observation in observations]
        checks['real_reconnect_readiness_handler'] = ready.is_set() and agent.session.connected
        checks['both_original_rpc_results_pending'] = all(not task.done() for task in captured_tasks)
        pumped = asyncio.Event()
        assert view.call_later(pumped.set)
        async with asyncio.timeout(5):
            await pumped.wait()
            editor.focus(scroll_visible=False)
            await pilot.press('x')
        checks['conversation_pump_and_editor_progress'] = (
            pumped.is_set() and editor.text != text
            and editor.document is document and editor.history is history)
        editor.undo()
        checks['unsent_draft_and_undo_restored'] = editor.text == text
        resized.clear()
        async with asyncio.timeout(5):
            await pilot.resize_terminal(size.width - 8, size.height - 2)
            await resized.wait()
        checks['actual_conversation_resize_while_reads_pending'] = (
            app.size.width == size.width - 8 and app.size.height == size.height - 2
            and all(not task.done() for task in captured_tasks))
        checks['original_agent_and_unfenced_frame'] = (
            view.agent is agent and not app._batch_count
            and not app.workspace_chrome.native._lock.locked())
        # Close the actual registered source, not merely its observer wrapper.
        # Capture Tasks before original close clears the observation's fields.
        async with asyncio.timeout(20):
            await app.workspace_sessions.close(source.id)
        checks['source_close_cancelled_and_joined_reads'] = all(
            task.done() and task.cancelled() for task in captured_tasks)
        checks['source_close_revoked_observation_custody'] = all(
            observation.view is None and observation.task is None for observation in observations)
        checks['actual_source_and_view_retired'] = (
            source.id not in app.workspace_sessions.views and not view.is_attached)
        assert all(checks.values()), checks
    finally:
        release.set()
        await asyncio.gather(*captured_tasks, return_exceptions=True)
        for observation, original in zip(observations, original_reads):
            observation.read = original
        Conversation.on_agent_ready, Conversation.on_resize = original_ready, original_resize
        (evidence / 'pending-readiness.json').write_text(json.dumps({
            'checks': checks,
            'pending_work': 'actual RPC results held before observation publication',
            'watch_agent_ready_branch_exercised': False,
            'provider_or_native_input': False,
            'scope': 'Real AgentReady Conversation callbacks/input/resize/source close; no latency or pixels claim',
        }, indent=2))


if __name__ == '__main__':
    if '--private-original-readiness' in sys.argv:
        from original_turn_resource_real_installed_pilot import main
        assert os.environ['AC_REAL_READ_ONLY_CUSTODY'] == '1'
        asyncio.run(main(readonly_acceptance=pending_readiness))
    else:
        from compaction_summary_stream_native_installed_pilot import reconnect_cancelled_source
        from native_loaded_return_cache_pilot import PaintedReturnApp
        asyncio.run(reconnect_cancelled_source(app_type=PaintedReturnApp,
                                             after_cold_load=held_original_read, headless=False))
