"""Textual-facing: the project tree's filter follows its root, and a hidden session's tree defers its directory reload until shown."""

from pathlib import Path

from toad.core import input_events

from support.textual_steps import reveal_project_tree
from support.workspace import Workspace


def project_with_ignored_cache(workspace: Workspace) -> Path:
    project = workspace.project
    (project / ".gitignore").write_text("*.cache\n")
    nested = project / "nested"
    nested.mkdir()
    (nested / "output.cache").touch()
    admitted = nested / "source.py"
    admitted.touch()
    return admitted


async def test_changing_the_tree_root_replaces_the_filter_with_that_roots_rules(
    workspace: Workspace,
) -> None:
    admitted = project_with_ignored_cache(workspace)
    async with workspace.app(size=(100, 40)) as ui:
        tree = await reveal_project_tree(ui)
        assert tree.path_filter is not None
        assert not tree.path_filter.match(admitted)
        assert tree.path_filter.match(admitted.with_name("output.cache"))
        other = workspace.roots.attempt / "other"
        other.mkdir()
        (other / "new.py").touch()
        tree.path = other
        await ui.until(lambda: not tree.path_filter.match(other / "new.py"), why="the filter of the new root")
        assert tree.path_filter.match(admitted)


async def test_hidden_session_defers_the_tree_reload_until_it_is_shown(
    workspace: Workspace,
) -> None:
    project_with_ignored_cache(workspace)
    async with workspace.app(size=(100, 40)) as ui:
        app, _ = ui.textual
        owner = ui.selected_tab
        session = app.selected_session
        tree = await reveal_project_tree(ui)
        await tree.wait_path_ready()

        def listed(path: Path) -> bool:
            return any((entry := node.data) is not None and entry.path == path
                       for node in tree.root.children)

        tree.root.expand()
        await ui.until(lambda: listed(workspace.project / "nested"), why="the expanded project root")
        await ui.new_session()
        added = workspace.project / "arrived.py"
        added.touch()
        session.publish_core(input_events.ProjectDirectoryUpdated())
        await ui.step()
        assert tree._directory_dirty and not tree._refresh_scheduled
        assert not listed(added)
        await ui.select_tab(owner)
        # Panels may retain or reconstruct their widget; query the current owner.
        tree = await reveal_project_tree(ui)
        await ui.until(lambda: listed(added), why="the new file after returning to its session")
        assert not tree._directory_dirty
