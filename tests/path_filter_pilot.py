"""Cross-project filters terminate and hidden project views defer filesystem refreshes."""

import asyncio
import os
import tempfile
from pathlib import Path

from toad import messages
from toad.app import ToadApp
from toad.path_filter import PathFilter
from toad.screens.main import MainScreen
from toad.widgets.project_directory_tree import ProjectDirectoryTree


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-path-filter-") as directory:
        root = Path(directory)
        project = root / "project"
        project.mkdir()
        (project / ".git").write_text("gitdir: elsewhere\n")
        (project / ".gitignore").write_text("*.cache\n")
        nested = project / "nested"
        nested.mkdir()
        ignored = nested / "output.cache"
        ignored.touch()
        admitted = nested / "source.py"
        admitted.touch()
        path_filter = PathFilter.from_git_root(nested)
        assert path_filter.match(ignored)
        assert not path_filter.match(admitted)
        assert path_filter.match(root / "other" / "file.py")
        assert path_filter.get_path_specs(Path("/")) == ()
        relative = PathFilter(Path("."))
        relative.match(Path.cwd() / "README.md")  # Previously recursed past /.
        os.environ.update(
            XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
            XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"),
        )
        app = ToadApp(project_dir=str(project))
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            owner = app.current_mode
            old_screen = app.screen
            from runtime_fixture import reveal_project_tree
            await reveal_project_tree(app, pilot)
            tree = old_screen.query_one("#project_directory_tree", ProjectDirectoryTree)
            assert tree.path_filter is not None
            other = root / "other"
            other.mkdir()
            (other / "new.py").touch()
            tree.path = other
            await pilot.pause()
            assert not tree.path_filter.match(other / "new.py")
            assert tree.path_filter.match(admitted)
            await app.new_session_screen(lambda: MainScreen(project))
            await pilot.pause()
            calls = []
            original = tree.reload

            def reload():
                calls.append(True)
                return original()

            tree.reload = reload
            old_screen.post_message(messages.ProjectDirectoryUpdated())
            await pilot.pause()
            assert not calls and tree._directory_dirty
            await app.switch_mode(owner)
            await pilot.pause()
            assert len(calls) == 1 and not tree._directory_dirty
    print("path filters: bounded ancestry, worktree ignore rules, root changes, lazy hidden refresh passed")


if __name__ == "__main__":
    asyncio.run(main())
