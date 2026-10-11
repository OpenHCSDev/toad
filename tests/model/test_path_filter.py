"""Path filters terminate across projects and follow the worktree's ignore rules."""

from pathlib import Path

from toad.path_filter import PathFilter


def test_filter_from_a_nested_directory_applies_the_git_roots_ignore_rules(tmp_path):
    project = tmp_path / "project"
    nested = project / "nested"
    nested.mkdir(parents=True)
    (project / ".git").write_text("gitdir: elsewhere\n")
    (project / ".gitignore").write_text("*.cache\n")
    ignored = nested / "output.cache"
    ignored.touch()
    admitted = nested / "source.py"
    admitted.touch()
    path_filter = PathFilter.from_git_root(nested)
    assert path_filter.match(ignored)
    assert not path_filter.match(admitted)
    assert path_filter.match(tmp_path / "other" / "file.py")
    assert path_filter.get_path_specs(Path("/")) == ()


def test_a_relative_root_does_not_recurse_past_the_filesystem_root():
    PathFilter(Path(".")).match(Path.cwd() / "README.md")  # Previously recursed past /.
