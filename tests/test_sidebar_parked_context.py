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


def test_context_detail_retains_native_reader_through_fresh_reads_and_tab_return(tmp_path, monkeypatch):
    """Read real imported provenance; retain native paint without masking it."""
    import json
    import sys
    import threading
    from agent_comms.importing import ImportFormat, ImportedSessionMetadata
    from textual.document._document import Selection
    from toad.app import ToadApp as ActualToadApp
    from toad.widgets.context_explorer import ContextDetail
    from test_context_manifest_navigation import select_context_source
    from l0a_native_installed_pilot import until

    async def mounted():
        project = tmp_path / "project"
        project.mkdir()
        source = tmp_path / "authored-context.jsonl"
        text = "\n".join(f"RETAINED_CONTEXT_{i:03d}: original instruction" for i in range(80))
        records = (
            {"type": "session_meta", "payload": {"id": "retained-context", "cwd": str(project)}},
            {"type": "response_item", "payload": {"type": "message", "role": "developer", "content": text}},
            {"type": "response_item", "payload": {"type": "message", "role": "user", "content": "Authored saved question"}},
        )
        source.write_text("".join(json.dumps(record) + "\n" for record in records))
        original = source.read_bytes()
        service = Comms(tmp_path / "wire")
        service.messaging.initialize_private_initial_protocol()
        imported = service.threads.import_thread(source, ImportFormat.CODEX, name="context-owner")
        for key in tuple(os.environ):
            if key.startswith("AGENT_COMMS_"):
                monkeypatch.delenv(key)
        for key, value in {
            "AGENT_COMMS_ROOT": service.root, "TOAD_TEST_ATTEMPT": tmp_path,
            "XDG_CONFIG_HOME": tmp_path / "config", "XDG_STATE_HOME": tmp_path / "state",
            "XDG_DATA_HOME": tmp_path / "data", "XDG_CACHE_HOME": tmp_path / "cache",
        }.items():
            monkeypatch.setenv(key, str(value))
        app = ActualToadApp(project_dir=str(project))
        async with app.run_test(size=(130, 44)) as pilot:
            await app.selected_session.wait_content_ready()
            screen = app.selected_session
            screen.initial_coordination_root = str(service.root)
            screen.on_comms_session_named(imported.thread)
            sidebar = screen.query_one(SessionThreadSidebar)
            sidebar.reveal()
            await sidebar.wait_content_ready()
            explorer = sidebar.query_one(ContextExplorer)
            explorer.query_ancestor(SideBarCollapsible).collapsed = False
            tree = explorer.query_one(ContextTree)
            key = ContextInspection.read(service, imported.thread).imported()[0].key
            await until(pilot, lambda: key in tree.context_nodes)
            await select_context_source(pilot, tree, key)
            area = explorer.query_one(ContextDetail)
            await until(pilot, lambda: "RETAINED_CONTEXT_079" in area.text)
            area.scroll_visible(animate=False, immediate=True)
            area.selection = Selection((6, 0), (6, 12))
            area.scroll_to(y=10, animate=False, immediate=True)
            await pilot.pause()
            await until(pilot, lambda: not any(worker.node is area and not worker.is_finished
                                               for worker in area.workers))
            document, wrapped = area.document, area.wrapped_document
            selection, reader = area.selection, area.scroll_offset
            node = tree.context_nodes[key]
            counts = {"authenticated_source_reads": 0, "loading_covers": 0}
            read_code = ImportedSessionMetadata.public_source_text.__code__

            def trace(frame, event, argument):
                if event != "call":
                    return
                if frame.f_code is read_code:
                    counts["authenticated_source_reads"] += 1
                if frame.f_code.co_name == "_cover" and frame.f_locals.get("self") is area:
                    counts["loading_covers"] += 1

            threading.setprofile_all_threads(trace)
            try:
                # Refresh the real inspection/native refusal and selected source;
                # no captured model, backend method or native renderer is replaced.
                for _ in range(3):
                    before = counts["authenticated_source_reads"]
                    await explorer._read(force=True).wait()
                    await until(pilot, lambda: counts["authenticated_source_reads"] > before
                                and not explorer._working("context-detail"))
                    assert tree.context_nodes[key] is node
                    assert area.document is document and area.wrapped_document is wrapped, (
                        wrapped._width, area.wrapped_document._width, area.wrap_width,
                        wrapped._tab_width, area.wrapped_document._tab_width, area.size)
                    assert area.selection == selection and area.scroll_offset == reader
                    assert not area.loading and area._cover_widget is None
                state = explorer.state
                await app.session_navigation.new(lambda: MainScreen(project))
                await app.select_session(screen.id)
                await pilot.pause()
                assert sidebar.query_one(ContextExplorer) is explorer
                assert explorer.query_one(ContextTree) is tree
                assert tree.context_nodes[key] is node
                assert area.document is document and area.wrapped_document is wrapped
                assert area.selection == selection and area.scroll_offset == reader
                assert explorer.state.presentation_current(state)
                assert "Current detail unavailable:" in explorer.state.status
                assert counts["loading_covers"] == 0
            finally:
                threading.setprofile_all_threads(None)
            assert source.read_bytes() == original
            # Change only this authored original file. Its existing provenance
            # reader must refuse it rather than keep painting it as current.
            source.write_text(source.read_text().replace("RETAINED_CONTEXT_079", "CHANGED_CONTEXT_079"))
            await explorer._show_detail(node.data).wait()
            assert "Selected context detail unavailable:" in area.text
            assert "changed or is unavailable" in area.text
            assert area.document is not document
            receipt = dict(counts, document_reused=True, wrapped_resource_reused=True,
                           tree_node_reused=True, reader_selection_retained=True,
                           warm_tab_return=True, changed_source_refused=True, provider_inputs=0,
                           scope="actual imported-source App; current SDK replacement remains unqualified")
            (tmp_path / "context-retention.json").write_text(json.dumps(receipt, indent=2) + "\n")
            print(json.dumps(receipt), flush=True)
            assert app._exception is None
    asyncio.run(mounted())
