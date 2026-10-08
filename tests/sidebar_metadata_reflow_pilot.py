"""Real disclosure retains native rows; source changes retire them.

Private canonical stores and native Pilot clicks, without membership mocks.
The observation owner pauses automatic reads only for the unchanged-source
gesture profile; source updates use real reads.
"""
import asyncio
from collections import Counter
import cProfile
import json
import os
from pathlib import Path
import sys
from time import perf_counter

from agent_comms.activity import ActivityState
from agent_comms.comms import Comms
from agent_comms.relationships import AddRelationshipEdit, RemoveRelationshipEdit
from agent_comms.threads import Thread
from runtime_fixture import ToadApp, wait_channel_roster
from toad.sidebar_preparation import ThreadRowInput, prepare_thread_presentation
from toad.widgets.comms_sidebar import ChannelGroup
from toad.widgets.session_sidebar import ThreadStatusRow
from toad.widgets.session_thread_sidebar import SessionThreadSidebar
from toad.widgets.side_bar import SideBar
from toad.widgets.thread_comms import ThreadCommsSidebar
from toad.widgets.comms_chat import session_thread_name


async def until(pilot, condition):
    async with asyncio.timeout(12):
        while not condition():
            await pilot.pause(.02)


async def gesture(pilot, group, expanded):
    group.disclosure.scroll_visible(animate=False, immediate=True)
    await pilot.pause(.02)
    assert group.expanded is not expanded
    started = perf_counter()
    assert await pilot.click(group.disclosure)
    await until(pilot, lambda: group.expanded is expanded
                and group.member_container.display is expanded
                and not group.member_lock.locked())
    await pilot.pause(.02)
    return (perf_counter() - started) * 1000


async def main(root):
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    for key in tuple(os.environ):
        if key.startswith('AGENT_COMMS_'):
            del os.environ[key]
    os.environ.update(AGENT_COMMS_ROOT=str(root / 'w'),
        TOAD_TEST_ATTEMPT=str(root), XDG_CONFIG_HOME=str(root / 'config'),
        XDG_STATE_HOME=str(root / 'state'), XDG_DATA_HOME=str(root / 'data'),
        XDG_CACHE_HOME=str(root / 'cache'))
    service = Comms(root / 'w', private_initial_writes=True)
    service.messaging.initialize_private_initial_protocol()
    for index in range(24):
        service.registry.declare(Thread(f'member-{index:02}',
            frozenset({'team', 'unopened'}), str(root)))
    original = service.registry.declare(Thread(session_thread_name(root), frozenset(), str(root)))
    app = ToadApp(project_dir=str(root))
    profile = cProfile.Profile()
    async with app.run_test(size=(140, 48)) as pilot:
        await app.selected_session.wait_content_ready()
        source = app.selected_session
        await app.session_navigation.new(lambda: source.spawn(root=str(service.root)),
            original=(str(service.root), original.incarnation))
        app.screen.query_one('#channels-sidebar', SideBar).reveal()
        sidebar = await wait_channel_roster(app, pilot)
        await sidebar.observation.sync()
        group = sidebar.projection.channels['#team'].query_ancestor(ChannelGroup)
        unopened = sidebar.projection.channels['#unopened'].query_ancestor(ChannelGroup)
        assert not unopened.expanded and not unopened._members
        sidebar.observation.set_enabled(False)
        await until(pilot, lambda: not sidebar.observation.pending)
        if not group.expanded:
            await gesture(pilot, group, True)
        await until(pilot, lambda: len(group._members) == 24)
        rows = dict(group._members)
        prepared = {name: row.thread_preparation(row.retained_thread_presentation(
            sidebar.projection.snapshot.all_people[name])) for name, row in rows.items()}
        sidebar.pointer_select(rows['member-00'], control=True)
        calls = Counter()
        watched = {ThreadRowInput.presentation.__code__: 'person_captures',
                   prepare_thread_presentation.__code__: 'row_preparations',
                   ThreadStatusRow.__init__.__code__: 'row_constructions'}
        monitor = sys.monitoring
        monitor.use_tool_id(monitor.COVERAGE_ID, 'sidebar-disclosure')
        monitor.register_callback(monitor.COVERAGE_ID, monitor.events.PY_START,
            lambda code, offset: calls.update((watched[code],)))
        for code in watched:
            monitor.set_local_events(monitor.COVERAGE_ID, code, monitor.events.PY_START)
        try:
            profile.enable()
            collapse_ms = await gesture(pilot, group, False)
            assert dict(group._members) == rows
            assert all(row.is_attached and not row.is_navigation_row() for row in rows.values())
            assert not any(row in sidebar.projection.rows for row in rows.values())
            assert not any(row in sidebar.projection.thread_rows for row in rows.values())
            assert not any(choice.target.startswith('member-')
                           for choice in sidebar.navigation.state.selected_targets)
            expand_ms = await gesture(pilot, group, True)
            for name, row in rows.items():
                assert group._members[name] is row
                assert row.thread_preparation(row.retained_thread_presentation(
                    sidebar.projection.snapshot.all_people[name])) is prepared[name]
            assert not calls, dict(calls)
        finally:
            profile.disable()
            for code in watched:
                monitor.set_local_events(monitor.COVERAGE_ID, code, 0)
            monitor.free_tool_id(monitor.COVERAGE_ID)
            profile.dump_stats(root / 'disclosure.pstats')

        await gesture(pilot, group, False)
        old = service.registry.require('member-23')
        service.registry.unregister(old.name)
        service.registry.delete_originals((service.registry.require(old.name),))
        successor = service.registry.declare(Thread(old.name, old.tags, old.worktree))
        changed = service.registry.require('member-22')
        service.registry.declare(Thread(changed.name, frozenset({'unopened'}), changed.worktree))
        service.agents.set_activity('member-00', ActivityState.WORKING, 'Actual changed status')
        sidebar.observation.set_enabled(True)
        await sidebar.observation.sync()
        await until(pilot, lambda: 'member-22' not in group._members
                    and group._members['member-23'].thread_incarnation == successor.incarnation)
        assert not rows['member-22'].is_attached and not rows['member-23'].is_attached
        assert not unopened._members
        await gesture(pilot, group, True)
        assert group._members['member-00'].busy
        assert 'Actual changed status' in group._members['member-00'].content.plain

        owner = app.selected_session._comms_thread
        service.relationships.edit(owner, AddRelationshipEdit, 'member-00', 'Real private relation')
        right = app.selected_session.query_one(SessionThreadSidebar)
        right.reveal()
        await right.wait_content_ready()
        tree = right.query_one(ThreadCommsSidebar)
        await until(pilot, lambda: 'collaborating' in tree.groups
                    and tree.groups['collaborating'].rows)
        relation = tree.groups['collaborating']
        relation_rows = dict(relation.rows)
        await gesture(pilot, relation, False)
        assert relation.rows == relation_rows
        assert not any(row in tree._ordered_rows() for row in relation_rows.values())
        await gesture(pilot, relation, True)
        assert relation.rows == relation_rows
        await gesture(pilot, relation, False)
        service.relationships.edit(owner, RemoveRelationshipEdit, 'member-00')
        tree.refresh_relationships(force=True)
        await until(pilot, lambda: not relation.rows)
        assert all(not row.is_attached for row in relation_rows.values())
        other = Comms(root / 'other', private_initial_writes=True)
        other.messaging.initialize_private_initial_protocol()
        await sidebar.observation.bind(other)
        assert not sidebar.query(ChannelGroup)
        assert not sidebar.projection.rows
        assert all(not row.is_attached for row in group._members.values())
        assert app._exception is None
        result = dict(collapse_ms=collapse_ms, expand_ms=expand_ms,
            unchanged_disclosure_calls=dict(calls), retained_rows=24,
            native_row_and_prepared_identity_preserved=True,
            hidden_selection_ranges_animation_excluded=True,
            closed_membership_and_incarnation_retired=True,
            unopened_groups_lazy=True, changed_live_status_painted=True,
            relationship_rows_retained_and_stale_rows_retired=True,
            rebind_retires_original_roster=True,
            strength='private source native Pilot and compositor; not physical terminal latency')
    (root / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    asyncio.run(main(Path(sys.argv[1])))
