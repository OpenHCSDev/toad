"""Final changed carrier and context disclosure; existing real native fixture."""
import asyncio
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests'))
sys.path.insert(0, str(ROOT / 'evidence/headless-agent-services-u2-20261003'))
from installed_services import InstalledApp
from l0a_native_installed_pilot import main, until
from toad.core_event_carrier import CoreEventMessage
from toad.core.events import SessionSelected
from toad.widgets.context_explorer import ContextExplorer
from toad.widgets.session_thread_sidebar import SessionThreadSidebar
from toad.widgets.side_bar import SideBarToggle, SideBarCollapsible


async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    started = time.monotonic()
    sidebar = app.selected_session.query_one(SessionThreadSidebar)
    if sidebar.collapsed:
        assert await pilot.click(sidebar.query_one(SideBarToggle))
    await until(pilot, lambda: app.selected_session.query_one_optional(ContextExplorer) is not None)
    explorer = app.selected_session.query_one(ContextExplorer)
    streams = {subscription.stream for subscription in explorer._core_subscriptions}
    assert streams == {app.events, app.coordination_access.events}
    subscription = next(s for s in explorer._core_subscriptions if s.stream is app.events)
    message = CoreEventMessage(SessionSelected(app.selected_mode), subscription)
    context, named = object(), object()
    seen, workers = [], []

    def sync_handler(value, resource, *, original):
        assert value is message and resource is context and original is named
        seen.append('sync')

    async def async_handler(value, resource, *, original):
        assert value is message and resource is context and original is named
        seen.append('async')

    def worker_handler(value, resource, *, original):
        assert value is message and resource is context and original is named
        async def owned_work():
            seen.append('owned-worker')
        worker = app.run_worker(owned_work())
        workers.append(worker)
        return worker

    def no_arguments():
        seen.append('no-arguments')

    result = await explorer.consume_handlers(
        message, [sync_handler, async_handler, worker_handler], context, original=named)
    assert result is message
    # Textual truncates positional callback inputs. Supplied keyword arguments
    # remain the declared handler contract; they aren't silently discarded.
    assert await explorer.consume_handlers(message, [no_arguments], context) is message
    await workers[0].wait()
    assert sorted(seen) == ['async', 'no-arguments', 'owned-worker', 'sync']
    panel = explorer.query_ancestor(SideBarCollapsible)
    panel.collapsed = False
    await pilot.pause()
    assert explorer.is_mounted and explorer.presentation_visible()
    # Receive the original application's typed publication via its native pump.
    app.events.publish(SessionSelected(app.selected_mode))
    await pilot.pause()
    assert app._exception is None
    acquired = tuple(explorer._core_subscriptions)
    await explorer.remove()
    assert not explorer._core_subscriptions and all(not s.active for s in acquired)
    assert not requests
    Path(os.environ['L0A_EVIDENCE'], 'event-consumer-receipt.json').write_text(json.dumps({
        'result': 'PASS', 'elapsed_seconds': time.monotonic() - started,
        'actual_installed_native_sidebar_disclosure_mounted_explorer': True,
        'canonical_coordination_and_application_streams': True,
        'native_pump_typed_publication_consumed': True,
        'borrowed_positional_keyword_context_exact': True,
        'sync_async_callbacks_and_original_worker_return': seen,
        'zero_argument_positional_truncation': True,
        'original_subscriptions_retired_on_unmount': True,
        'provider_requests': len(requests),
        'scope': 'Real installed Toad/ACP/Pi; native Pilot sidebar click and event carrier. No repeated permission/PTY journey, prompt, public source or provider input; context content quality/physical pixel readability not claimed.'
    }, indent=2) + '\n')


if __name__ == '__main__':
    asyncio.run(main(app_type=InstalledApp, acceptance=acceptance,
                    fixture_stage=os.environ['U356_FIXTURE_ROOT'], provider_request_budget=0))
