"""Measure real private backend publications reaching the mounted Channels view.

No provider, native input, substituted service or mocked renderer participates.
"""

import asyncio
import json
import os
from pathlib import Path
import sys
import inspect
import cProfile
from collections import Counter
from time import perf_counter

from agent_comms.comms import Comms
from agent_comms.threads import Thread
from runtime_fixture import ToadApp
from toad.widgets.channels_sidebar import ChannelsSidebar
from toad.widgets.comms_sidebar import ChannelGroup
from toad.screens.main import MainScreen
from toad.sidebar_projection import SidebarProjection
from toad.sidebar_preparation import ThreadRowsWork
from toad.widgets.thread_comms import ThreadCommsSidebar
from toad.widgets.session_thread_sidebar import SessionThreadSidebar
from toad.widgets.side_bar import SideBarCollapsible


async def main(output):
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    project = output / "project"
    project.mkdir()
    for key in tuple(os.environ):
        if key.startswith("AGENT_COMMS_"):
            del os.environ[key]
    os.environ.update(
        AGENT_COMMS_ROOT=str(output / "wire"), TOAD_TEST_ATTEMPT=str(output),
        XDG_CONFIG_HOME=str(output / "config"), XDG_STATE_HOME=str(output / "state"),
        XDG_DATA_HOME=str(output / "data"), XDG_CACHE_HOME=str(output / "cache"),
    )
    service = Comms(output / "wire", private_initial_writes=True)
    service.messaging.initialize_private_initial_protocol()
    tags = frozenset({"shared", "design", "code", "review"})
    owners = []
    for i in range(24):
        worktree = project if i == 0 else project / f"agent-{i:02}"
        worktree.mkdir(exist_ok=True)
        owners.append(service.registry.declare(Thread("project" if i == 0 else f"agent-{i:02}", tags, str(worktree))))
    owners = tuple(owners)
    app = ToadApp(project_dir=str(project))
    gaps, emitted = [], []
    async with app.run_test(size=(140, 48)) as pilot:
        await app.selected_session.wait_content_ready()
        first = app.selected_session
        first.initial_coordination_root = str(service.root)
        def declared_source(owner):
            source = MainScreen(Path(owner.worktree))
            source.initial_coordination_root = str(service.root)
            return source
        for owner in owners[1:6]:
            await app.session_navigation.new(lambda owner=owner: declared_source(owner))
        await app.select_session(first.id)
        channels = app.screen.query_one(ChannelsSidebar)
        channels.reveal()
        await channels.wait_content_ready()
        roster = channels.roster
        await roster.observation.sync()
        for group in tuple(roster.query(ChannelGroup)):
            await group.reveal_members()
        right = app.selected_session.query_one(SessionThreadSidebar)
        right.reveal()
        await right.wait_content_ready()
        relationships = right.query_one(ThreadCommsSidebar)
        relationships.query_ancestor(SideBarCollapsible).collapsed = False
        await pilot.pause()
        relationships.refresh_relationships(force=True)
        if relationships._refresh_task is not None:
            await relationships._refresh_task
        assert relationships._snapshot is not None
        assert relationships.owner == owners[0].name
        assert Path(relationships._snapshot.root) == service.root
        row_ids = {group.row.target_name: {name: id(row) for name, row in group._members.items()}
                   for group in roster.query(ChannelGroup)}
        elapsed = []
        running = True
        async def responsiveness():
            while running:
                start = perf_counter()
                await asyncio.sleep(.01)
                gaps.append(perf_counter() - start)
        sampler = asyncio.create_task(responsiveness())
        profile = cProfile.Profile() if os.environ.get("SIDEBAR_PROFILE") else None
        calls = Counter()
        watched = {
            SidebarProjection.sync_sessions.__code__: "local_route_reconciliations",
            SidebarProjection.rebuild.__code__: "channel_publications",
            ThreadRowsWork.capture.__func__.__code__: "thread_presentation_captures",
            ThreadCommsSidebar._refresh.__code__: "relationship_refreshes",
        }
        route_code = SidebarProjection.sync_sessions.__code__
        route_lines, route_start = inspect.getsourcelines(SidebarProjection.sync_sessions)
        route_rebuild_line = route_start + next(i for i, line in enumerate(route_lines)
                                               if "await self.rebuild(projected)" in line)
        monitor = sys.monitoring
        monitor_id = monitor.COVERAGE_ID if profile is not None else monitor.PROFILER_ID
        monitor.use_tool_id(monitor_id, "private-sidebar-fanout")
        monitor.register_callback(monitor_id, monitor.events.PY_START,
                                  lambda code, offset: calls.update((watched[code],)))
        monitor.register_callback(monitor_id, monitor.events.LINE,
                                  lambda code, line: calls.update(("local_route_row_rebuilds",))
                                  if line == route_rebuild_line else None)
        for code in watched:
            monitor.set_local_events(monitor_id, code, monitor.events.PY_START
                                     | (monitor.events.LINE if code is route_code else 0))
        try:
            if profile is not None:
                profile.enable()
            # Real tab metadata belongs to SessionTracker, independently of wire
            # rows. These authored titles are not provider activity markers.
            routes = dict(roster.projection.snapshot.session_threads)
            for view in app.workspace_sessions.views.values():
                app.session_tracker.update_session(view.id, title=f"Private tab {view.id}")
            await pilot.pause(.1)
            assert dict(roster.projection.snapshot.session_threads) == routes
            metadata_calls = dict(calls)
            assert calls["local_route_reconciliations"] == len(app.workspace_sessions.views)
            assert calls["local_route_row_rebuilds"] == 0
            # Each committed message has an original declared sender and frozen
            # backend audience. No made-up provider/status marker drives paint.
            for round_number in range(4):
                start = perf_counter()
                messages = await asyncio.gather(*(asyncio.to_thread(
                    service.messaging.send_initial_cohort, owner.name, "#shared",
                    f"Private backend response {round_number} from {owner.name}",
                ) for owner in owners))
                emitted.extend(message.message_id for message in messages)
                async with asyncio.timeout(20):
                    while (roster.projection.snapshot is None or
                           roster.projection.snapshot.wire.channel_unread.get("#shared", 0)
                           < len(emitted)):
                        await pilot.pause(.02)
                elapsed.append(perf_counter() - start)
            await pilot.pause(.1)
        finally:
            if profile is not None:
                profile.disable()
                profile.dump_stats(output / "ui.pstats")
            for code in watched:
                monitor.set_local_events(monitor_id, code, 0)
            monitor.free_tool_id(monitor_id)
            running = False
            await sampler
        for group in roster.query(ChannelGroup):
            assert {name: id(row) for name, row in group._members.items()} == row_ids[group.row.target_name]
        # Closing a real native session changes the route projection. The
        # surviving row widgets still belong to the same original groups.
        departing = next(view for view in app.workspace_sessions.views.values()
                         if view is not app.selected_session)
        await app.session_navigation.close(departing.id)
        await pilot.pause(.1)
        assert departing.id not in roster.projection.snapshot.session_threads
        assert app._exception is None
        # Read back the exact private producer through the original certified log.
        committed = tuple(service.bus.log.full_history())
        assert {message.message_id for message in committed} >= set(emitted)
        ordered = sorted(gaps)
        result = {
            "declared_threads": len(owners), "committed_backend_messages": len(emitted),
            "retained_conversations": sum(view.presentation.widget is not None
                                           for view in app.workspace_sessions.views.values()
                                           if isinstance(view, MainScreen)),
            "owner_call_counts": dict(calls),
            "tab_metadata_owner_calls": metadata_calls,
            "relationship_groups": len(relationships.groups),
            "relationship_messages_observed": relationships._snapshot.history_messages,
            "channel_rows": len(tuple(roster.query(ChannelGroup))),
            "native_thread_rows": sum(len(group._members) for group in roster.query(ChannelGroup)),
            "publication_seconds": elapsed,
            "loop_gap_seconds": {"max": max(gaps), "p95": ordered[int(.95 * (len(ordered)-1))]},
            "row_identity_preserved": True, "provider_requests": 0,
            "strength": "private source headless App; not physical terminal or live provider streams",
        }
        (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result), flush=True)


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1])))
