"""Path filters use Git-relative scopes, including when the host path matches a rule."""

from pathlib import Path

import pytest

from agent_comms.repo import Repo
from toad.path_filter import PathFilter


@pytest.fixture
def git_project(tmp_path: Path) -> Path:
    project = tmp_path / "host.cache" / "project"
    project.mkdir(parents=True)
    Repo.git(project, "init", "-q")
    return project


def test_filter_from_a_nested_directory_applies_the_git_roots_ignore_rules(
    git_project: Path,
) -> None:
    nested = git_project / "nested"
    nested.mkdir()
    (git_project / ".gitignore").write_text("*.cache\n")
    ignored = nested / "output.cache"
    ignored.touch()
    admitted = nested / "source.py"
    admitted.touch()
    path_filter = PathFilter.from_git_root(nested)
    assert path_filter.match(ignored)
    assert not path_filter.match(admitted)
    assert path_filter.match(git_project.parent / "other" / "file.py")
    assert not path_filter.get_path_specs(Path("/"))


@pytest.mark.parametrize("relative", (
    "source.py", "root-only.py", "nested/root-only.py", "nested/nested-only.py",
    "nested/deeper/nested-only.py", "nested/drop.cache", "nested/keep.cache",
    "excluded/keep.cache",
))
def test_scoped_rules_and_negation_agree_with_git(git_project: Path, relative: str) -> None:
    (git_project / ".gitignore").write_text("/root-only.py\n*.cache\nexcluded/\n")
    nested = git_project / "nested"
    nested.mkdir()
    (nested / ".gitignore").write_text("/nested-only.py\n!keep.cache\n")
    excluded = git_project / "excluded"
    excluded.mkdir()
    (excluded / ".gitignore").write_text("!keep.cache\n")
    candidate = git_project / relative
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.touch()
    expected = Repo.answers(git_project, "check-ignore", "--no-index", "-q", relative)
    assert PathFilter.from_git_root(git_project).match(candidate) == expected


def test_a_nested_view_keeps_the_ancestor_ignore_files_anchor(git_project: Path) -> None:
    nested = git_project / "nested"
    nested.mkdir()
    (git_project / ".gitignore").write_text("/nested/rooted.py\n")
    candidate = nested / "rooted.py"
    candidate.touch()
    expected = Repo.answers(git_project, "check-ignore", "--no-index", "-q", "nested/rooted.py")
    assert PathFilter.from_git_root(nested).match(candidate) == expected


def test_linked_worktree_rules_use_the_worktrees_declaring_directory(
    git_project: Path, tmp_path: Path,
) -> None:
    Repo.git(git_project, "-c", "user.name=Path filter fixture",
             "-c", "user.email=path-filter@localhost", "commit", "--allow-empty", "-qm", "fixture")
    linked = tmp_path / "linked.cache" / "project"
    linked.parent.mkdir()
    Repo.git(git_project, "worktree", "add", "--detach", str(linked))
    (linked / ".gitignore").write_text("*.cache\n")
    for name in ("source.py", "output.cache"):
        candidate = linked / name
        candidate.touch()
        expected = Repo.answers(linked, "check-ignore", "--no-index", "-q", name)
        assert PathFilter.from_git_root(linked).match(candidate) == expected


def test_a_relative_root_does_not_recurse_past_the_filesystem_root() -> None:
    PathFilter(Path(".")).match(Path.cwd() / "README.md")
