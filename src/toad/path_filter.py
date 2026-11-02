from collections.abc import Mapping
from pathlib import Path
from os.path import abspath
import pathspec
import pathspec.patterns
from pathspec import GitIgnoreSpec
from pathspec.patterns.gitwildmatch import GitWildMatchPatternError

import rich.repr


def load_path_spec(git_ignore_path: Path) -> GitIgnoreSpec | None:
    """Get a path spec instance if there is a .gitignore file present.

    Args:
        git_ignore_path): Path to .gitignore.

    Returns:
        A `PathSpec` instance.
    """
    if git_ignore_path.is_file():
        try:
            spec_text = git_ignore_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return None
        try:
            spec = GitIgnoreSpec.from_lines(
                pathspec.patterns.GitWildMatchPattern, spec_text.splitlines()
            )
        except GitWildMatchPatternError:
            # A project .gitignore Toad cannot parse filters nothing.
            return None
        return spec
    return None


@rich.repr.auto
class PathFilter:
    """Filter paths according to .gitignore files."""

    def __init__(
        self, root: Path, path_specs: Mapping[Path, GitIgnoreSpec] | None = None
    ) -> None:
        self._root = Path(abspath(root))
        self._default_specs = {} if path_specs is None else dict(path_specs)
        self._path_specs: dict[Path, Mapping[Path, GitIgnoreSpec]] = {}

    def __rich_repr__(self) -> rich.repr.Result:
        yield (str(self._root),)

    @classmethod
    def from_git_root(cls, path: Path) -> PathFilter:
        """Load all path specs from parent directories up to the most recent directory with .git

        Args:
            path: A directory path.

        Returns:
            PathFilter instance.
        """
        path = Path(abspath(path))
        filter_root = path
        path_specs: dict[Path, GitIgnoreSpec] = {}
        while (parent := path.parent) != path:
            if (path_spec := load_path_spec(path / ".gitignore")) is not None:
                path_specs[path] = path_spec
            if (path / ".git").exists():
                break
            path = parent
        else:
            path_specs.clear()
        return cls(filter_root, dict(reversed(path_specs.items())))

    def get_path_specs(self, path: Path) -> Mapping[Path, GitIgnoreSpec]:
        """Get applicable specs in declaration order, keyed by their directory.

        Each spec retains the origin against which its patterns are interpreted.

        Args:
            path: A directory path

        Returns:
            A mapping from declaring directory to its spec.
        """
        path = Path(abspath(path))
        if not path.is_relative_to(self._root):
            return {}
        if (cached_path_specs := self._path_specs.get(path)) is not None:
            return cached_path_specs
        if path == self._root:
            path_specs: dict[Path, GitIgnoreSpec] = {}
            for origin, path_spec in self._default_specs.items():
                if not self._matches(origin, path_specs, directory=True):
                    path_specs[origin] = path_spec
        else:
            path_specs = dict(self.get_path_specs(path.parent))
        # Admission is cached per directory, not rechecked for every file.
        # Git never reads a deeper ignore file through an excluded directory.
        if path not in path_specs and not self._matches(path, path_specs, directory=True):
            if (path_spec := load_path_spec(path / ".gitignore")) is not None:
                path_specs[path] = path_spec
        self._path_specs[path] = path_specs
        return path_specs

    @staticmethod
    def _matches(path: Path, specs: Mapping[Path, GitIgnoreSpec], *, directory: bool) -> bool:
        ignored = False
        for origin, path_spec in specs.items():
            if path == origin:
                continue  # An ignore file does not match its own directory.
            relative = path.relative_to(origin).as_posix() + ("/" if directory else "")
            # Preserve the foreign parser's no-match / !rule / ignore answers.
            decision = path_spec.check_file(relative).include
            if decision is not None:
                ignored = decision
        return ignored

    def match(self, path: Path) -> bool:
        """Match a path againt the path filter.

        Returns:
            `True` if the path should be removed, `False` if it should be included.
        """
        path = Path(abspath(path))
        if path.name == ".git" or not path.is_relative_to(self._root):
            return True
        specs = self.get_path_specs(path if path == self._root else path.parent)
        return self._matches(path, specs, directory=path.is_dir())


if __name__ == "__main__":
    path_filter = PathFilter.from_git_root(Path("."))

    for path in Path(".").iterdir():
        print(path_filter.match(path), path)
    print(path_filter)
