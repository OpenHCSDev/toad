"""Measure publication fanout in the real private App, without provider inputs."""

import asyncio
from collections import Counter
import cProfile
import json
import os
from pathlib import Path
import sys
from time import perf_counter

from agent_comms.activity import ActivityState
from agent_comms.child_process import ProcessIdentity
from agent_comms.comms import Comms
from agent_comms.history_views import HistoryViews
from agent_comms.threads import Thread
from runtime_fixture import ToadApp, wait_channel_roster
from toad.sidebar_preparation import ThreadRowInput
from toad.widgets.comms_chat import session_thread_name
from toad.widgets.comms_sidebar import ChannelGroup, CommsSidebar
from toad.widgets.side_bar import SideBar


async def main(root):
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    for key in tuple(os.environ):
        if key.startswith('AGENT_COMMS_'):
            del os.environ[key]
    os.environ.update(AGENT_COMMS_ROOT=str(root / 'w'), TOAD_TEST_ATTEMPT=str(root),
        XDG_CONFIG_HOME=str(root / 'config'), XDG_STATE_HOME=str(root / 'state'),
        XDG_DATA_HOME=str(root / 'data'), XDG_CACHE_HOME=str(root / 'cache'))
    service = Comms(root / 'w', private_initial_writes=True)
    service.messaging.initialize_private_initial_protocol()
    for index in range(24):
        service.registry.declare(Thread(f'worker-{index:02}', frozenset({'team'}), str(root),
            process_identity=ProcessIdentity.capture(os.getpid())))
    original = service.registry.declare(Thread(session_thread_name(root), frozenset(), str(root)))
    app = ToadApp(project_dir=str(root))
    profile = cProfile.Profile()
    results = []
    async with app.run_test(size=(140, 48)) as pilot:
        await app.selected_session.wait_content_ready()
        source = app.selected_session
        await app.session_navigation.new(lambda: source.spawn(root=str(service.root)),
            original=(str(service.root), original.incarnation))
        first = app.selected_mode
        app.screen.query_one('#channels-sidebar', SideBar).reveal()
        sidebar = await wait_channel_roster(app, pilot)
        sidebar.observation.set_enabled(False)
        await sidebar.observation.sync()
        access = app.coordination_access
        access.timer.pause()
        if access.task is not None:
            await access.task
        acquired_service = access.service
        filters = (app.settings.sidebar.show_stopped, app.settings.sidebar.show_archived)
        calls = Counter()
        watched = {HistoryViews.viewer_snapshot.__code__: 'viewer_reads',
                   ThreadRowInput.presentation.__code__: 'person_captures'}
        monitor = sys.monitoring
        monitor.use_tool_id(monitor.COVERAGE_ID, 'publication-fanout')
        monitor.register_callback(monitor.COVERAGE_ID, monitor.events.PY_START,
            lambda code, offset: calls.update((watched[code],)))
        for code in watched:
            monitor.set_local_events(monitor.COVERAGE_ID, code, monitor.events.PY_START)
        try:
            profile.enable()
            for burst in range(3):
                for index in range(24):
                    service.agents.set_activity(f'worker-{index:02}', ActivityState.WORKING,
                        f'Published burst {burst}, member {index}')
                calls.clear()
                started = perf_counter()
                publications = await asyncio.gather(*(
                    access.read_sidebar(app, acquired_service, filters) for _ in range(8)))
                cuts = {publication.revision for publication in publications}
                assert calls['viewer_reads'] == len(cuts), dict(calls)
                assert calls['person_captures'] == 25 * len(cuts), dict(calls)
                acquisition_ms = (perf_counter() - started) * 1000
                before = calls.copy()
                captured = publications[-1]
                await sidebar.projection.publish(captured.project(app, acquired_service))
                await sidebar.projection.sync_sessions()
                await sidebar.projection.publish(captured.project(app, acquired_service))
                assert calls == before, (dict(before), dict(calls))
                group = sidebar.projection.channels['#team'].query_ancestor(ChannelGroup)
                if not group.expanded:
                    group.toggle_members()
                    await pilot.pause()
                assert len(group._members) == 24
                assert all(f'Published burst {burst}' in row.content.plain
                           for row in group._members.values())
                results.append({'consumers': 8, 'distinct_original_revisions': len(cuts),
                    **dict(calls), 'acquisition_ms': acquisition_ms,
                    'local_reprojection_extra_captures': 0})
        finally:
            profile.disable()
            for code in watched:
                monitor.set_local_events(monitor.COVERAGE_ID, code, 0)
            monitor.free_tool_id(monitor.COVERAGE_ID)
            profile.dump_stats(root / 'publication.pstats')

        # Hidden views retain paint, then borrow a fresh publication after
        # their original admission selects them again.
        await app.session_navigation.new(lambda: source.spawn(root=str(service.root)),
            original=(str(service.root), original.incarnation))
        second = app.selected_mode
        other = app.screen.query_one(CommsSidebar)
        other.observation.set_enabled(False)
        service.agents.set_activity('worker-00', ActivityState.THINKING, 'While first view hidden')
        await other.observation.sync()
        fresh = access.sidebar_snapshot
        await app.select_session(first)
        await sidebar.observation.sync()
        assert sidebar.projection.snapshot.row_inputs is fresh.row_inputs
        assert 'While first view hidden' in group._members['worker-00'].content.plain

        old = service.registry.require('worker-23')
        service.registry.unregister(old.name)
        service.registry.delete_originals((service.registry.require(old.name),))
        successor = service.registry.declare(Thread(old.name, old.tags, old.worktree))
        old_row = group._members[old.name]
        await sidebar.observation.sync()
        assert group._members[old.name].thread_incarnation == successor.incarnation
        assert not old_row.is_attached
        changed_filters = (not filters[0], filters[1])
        filtered = await access.read_sidebar(app, acquired_service, changed_filters)
        assert filtered is not fresh and filtered.wire.show_stopped == changed_filters[0]

        other_service = Comms(root / 'other', private_initial_writes=True)
        other_service.messaging.initialize_private_initial_protocol()
        os.environ['AGENT_COMMS_ROOT'] = str(other_service.root)
        current = access.service
        assert access.sidebar_snapshot is None
        try:
            await access.read_sidebar(app, acquired_service, filters)
        except ValueError:
            pass
        else:
            raise AssertionError('Replaced service supplied its old publication')
        await sidebar.observation.bind(current)
        await sidebar.observation.sync()
        assert not group.is_attached
        assert app._exception is None
        result = {'bursts': results, 'hidden_reopen_fresh': True,
            'incarnation_retired': True, 'filter_scope_distinct': True,
            'service_replacement_revoked': True, 'native_modes': [first, second],
            'strength': 'private source App and component acquisition; not installed CPU or physical latency'}
        (root / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result, indent=2))


if __name__ == '__main__':
    asyncio.run(main(Path(sys.argv[1])))
