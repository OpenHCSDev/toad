"""Real private sidebar acquisition and retained native-tree publication."""

import asyncio
import os
from dataclasses import replace

from agent_comms.comms import Comms
from agent_comms.relationships import AddRelationshipEdit
from agent_comms.threads import Thread
from runtime_fixture import ToadApp
from toad.core.context_inspection import ContextInspection, DetachedInspection, HoldingInspection
from toad.screens.main import MainScreen
from toad.widgets.context_explorer import ContextExplorer, ContextTree
from toad.widgets.session_thread_sidebar import SessionThreadSidebar
from toad.widgets.side_bar import SideBarCollapsible
from toad.widgets.thread_comms import ThreadCommsSidebar


def test_inspection_publication_tracks_source_not_observation_revision(tmp_path):
    service = Comms(tmp_path / "wire", private_initial_writes=True)
    service.registry.declare(Thread("owner", frozenset(), str(tmp_path)))
    service.messaging.initialize_private_initial_protocol()
    original = ContextInspection.read(service, "owner")
    captured = HoldingInspection(original, 1)
    assert captured.observe(2).presentation_current(captured)
    changed = replace(original, owner=replace(original.owner, created_at=2))
    assert not HoldingInspection(changed, 2).presentation_current(captured)
    assert not DetachedInspection().presentation_current(captured)


def test_context_preparation_survives_hidden_panel_and_warm_tab_return(tmp_path, monkeypatch):
    async def mounted():
        root = tmp_path / "wire"
        project = tmp_path / "project"
        project.mkdir()
        service = Comms(root, private_initial_writes=True)
        service.registry.declare(Thread("owner", frozenset(), str(project)))
        service.messaging.initialize_private_initial_protocol()
        for key in tuple(os.environ):
            if key.startswith("AGENT_COMMS_"):
                monkeypatch.delenv(key)
        for key, value in {
            "AGENT_COMMS_ROOT": root,
            "TOAD_TEST_ATTEMPT": tmp_path,
            "XDG_CONFIG_HOME": tmp_path / "config",
            "XDG_STATE_HOME": tmp_path / "state",
            "XDG_DATA_HOME": tmp_path / "data",
            "XDG_CACHE_HOME": tmp_path / "cache",
        }.items():
            monkeypatch.setenv(key, str(value))
        app = ToadApp(project_dir=str(project))
        async with app.run_test(size=(130, 44)) as pilot:
            await app.selected_session.wait_content_ready()
            screen = app.selected_session
            screen._comms_thread = "owner"
            screen.initial_coordination_root = str(root)
            sidebar = screen.query_one(SessionThreadSidebar)
            sidebar.reveal()
            await sidebar.wait_content_ready()
            explorer = sidebar.query_one(ContextExplorer)
            panel = explorer.query_ancestor(SideBarCollapsible)
            panel.collapsed = False
            await pilot.pause()
            assert explorer.presentation_visible()
            # Start the real read while visible, then hide its retained panel.
            # No delayed/mocked source or reconstructed Tree supplies the result.
            read = explorer._read()
            panel.collapsed = True
            await read.wait()
            for worker in tuple(explorer.workers):
                if worker.node is explorer and not worker.is_finished:
                    await worker.wait()
            tree = explorer.query_one(ContextTree)
            assert tree.root.children
            nodes = tuple(tree.root.children)
            state = explorer.state
            await app.session_navigation.new(lambda: MainScreen(project))
            assert explorer.is_attached
            await app.select_session(screen.id)
            assert sidebar.query_one(ContextExplorer) is explorer
            assert explorer.query_one(ContextTree) is tree
            assert tuple(tree.root.children) == nodes
            assert explorer.state is state
            panel.collapsed = False
            tree.scroll_visible(animate=False, immediate=True)
            await pilot.pause()
            assert tree in screen.screen._compositor.visible_widgets
            region, clip = screen.screen._compositor.visible_widgets[tree]
            region = region.intersection(clip)
            painted = "\n".join(strip.crop(region.x, region.right).text for strip in
                                screen.screen._compositor.render_strips()[region.y:region.bottom])
            assert "Context" in painted
            assert app._exception is None
    asyncio.run(mounted())


def test_relationship_preparation_finishes_in_retained_hidden_panel(tmp_path, monkeypatch):
    async def mounted():
        root = tmp_path / "wire"
        project = tmp_path / "project"
        project.mkdir()
        service = Comms(root, private_initial_writes=True)
        for name in ("owner", "peer"):
            service.registry.declare(Thread(name, frozenset(), str(project)))
        service.messaging.initialize_private_initial_protocol()
        for key in tuple(os.environ):
            if key.startswith("AGENT_COMMS_"):
                monkeypatch.delenv(key)
        for key, value in {
            "AGENT_COMMS_ROOT": root, "TOAD_TEST_ATTEMPT": tmp_path,
            "XDG_CONFIG_HOME": tmp_path / "config", "XDG_STATE_HOME": tmp_path / "state",
            "XDG_DATA_HOME": tmp_path / "data", "XDG_CACHE_HOME": tmp_path / "cache",
        }.items():
            monkeypatch.setenv(key, str(value))
        app = ToadApp(project_dir=str(project))
        async with app.run_test(size=(130, 44)) as pilot:
            await app.selected_session.wait_content_ready()
            screen = app.selected_session
            screen._comms_thread = "owner"
            screen.initial_coordination_root = str(root)
            sidebar = screen.query_one(SessionThreadSidebar)
            sidebar.reveal()
            await sidebar.wait_content_ready()
            relationships = sidebar.query_one(ThreadCommsSidebar)
            panel = relationships.query_ancestor(SideBarCollapsible)
            panel.collapsed = False
            relationships.scroll_visible(animate=False, immediate=True)
            await pilot.pause()
            if relationships._refresh_task is not None:
                await relationships._refresh_task
            service.relationships.edit("owner", AddRelationshipEdit, "peer", "Private source App")
            relationships.refresh_relationships()
            task = relationships._refresh_task
            assert task is not None and not task.done()
            panel.collapsed = True
            await task
            group = relationships.groups["collaborating"]
            key = next(key for key in group.rows if key[1] == "peer")
            row = group.rows[key]
            revision = relationships._revision
            await app.session_navigation.new(lambda: MainScreen(project))
            await app.select_session(screen.id)
            assert sidebar.query_one(ThreadCommsSidebar) is relationships
            assert relationships.groups["collaborating"] is group
            assert group.rows[key] is row
            assert relationships._revision == revision
            assert app._exception is None
    asyncio.run(mounted())
