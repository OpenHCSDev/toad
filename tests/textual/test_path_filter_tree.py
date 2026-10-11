"""Textual-facing: the project tree's filter follows its root, and a hidden session's tree defers its directory reload until shown."""

from toad.core import input_events

from support.textual_steps import reveal_project_tree


def project_with_git_root(workspace):
    project = workspace.project
    (project / ".git").write_text("gitdir: elsewhere\n")
    (project / ".gitignore").write_text("*.cache\n")
    nested = project / "nested"
    nested.mkdir()
    (nested / "output.cache").touch()
    admitted = nested / "source.py"
    admitted.touch()
    return admitted


async def test_changing_the_tree_root_replaces_the_filter_with_that_roots_rules(workspace):
    admitted = project_with_git_root(workspace)
    async with workspace.app(size=(100, 40)) as ui:
        tree = await reveal_project_tree(ui)
        assert tree.path_filter is not None
        other = workspace.roots.attempt / "other"
        other.mkdir()
        (other / "new.py").touch()
        tree.path = other
        await ui.until(lambda: not tree.path_filter.match(other / "new.py"), why="the filter of the new root")
        assert tree.path_filter.match(admitted)


async def test_hidden_session_defers_the_tree_reload_until_it_is_shown(workspace):
    project_with_git_root(workspace)
    async with workspace.app(size=(100, 40)) as ui:
        app, _ = ui.textual
        owner = ui.selected_tab
        session = app.selected_session
        tree = await reveal_project_tree(ui)
        await ui.new_session()
        calls = []
        reload = tree.reload

        def counted_reload():
            calls.append(True)
            return reload()

        tree.reload = counted_reload
        session.publish_core(input_events.ProjectDirectoryUpdated())
        await ui.step()
        assert not calls and tree._directory_dirty
        await ui.select_tab(owner)
        await ui.until(lambda: len(calls) == 1 and not tree._directory_dirty, why="exactly one reload on return")
