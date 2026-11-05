import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from itertools import islice
import os
from pathlib import Path
from typing import Iterable, Sequence


def longest_common_prefix(strings: list[str]) -> str:
    """
    Find the longest common prefix among a list of strings.

    Arguments:
        strings: List of strings

    Returns:
        The longest common prefix string
    """
    if not strings:
        return ""

    # Start with the first string as reference
    prefix: str = strings[0]

    # Compare with each subsequent string
    for current_string in strings[1:]:
        # Reduce prefix until it matches the start of current string
        while not current_string.startswith(prefix):
            prefix = prefix[:-1]
            if not prefix:
                return ""

    return prefix


class DirectoryReadTask:
    """A task to read a directory."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.done_event = asyncio.Event()
        self.directory_listing: list[Path] = []
        self._task: asyncio.Task | None = None

    def read(self) -> None:
        """Read the directory contents."""
        # TODO: Arbitary limit, to avoid stalling on very large directories
        # Should this be configurable?
        try:
            for path in islice(self.path.iterdir(), None, 10_000):
                self.directory_listing.append(path)
        except OSError:
            return

    def start(self) -> None:
        self._task = asyncio.create_task(
            self.run(), name=f"DirectoryReadTask({str(self.path)!r})"
        )

    async def run(self):
        try:
            await asyncio.to_thread(self.read)
        finally:
            self.done_event.set()

    async def wait(self) -> list[Path]:
        await self.done_event.wait()
        return self.directory_listing


class PathKinds(ABC):
    """Which listing entries a completion may offer: the shell command decides."""

    @abstractmethod
    def keeps(self, path: Path) -> bool: ...


class AnyPath(PathKinds):
    def keeps(self, path: Path) -> bool:
        return True


class FilesOnly(PathKinds):
    def keeps(self, path: Path) -> bool:
        return not path.is_dir()


class DirectoriesOnly(PathKinds):
    def keeps(self, path: Path) -> bool:
        return path.is_dir()


class CompletingEditor:
    """What a path completion needs from the editor whose last shell token it completes."""

    @abstractmethod
    def replace_text(self, text: str) -> None: ...

    @abstractmethod
    def offer(self, options: list[str]) -> None:
        """Show these options, or cycle them when they are already shown; none clears them."""


class PathCompletion(ABC):
    """What one Tab press does to a shell prompt's last token."""

    @abstractmethod
    def apply(self, editor: CompletingEditor, working_directory: Path, tokens: list[str], after: str) -> None: ...


@dataclass(frozen=True)
class ExtendedPath(PathCompletion):
    """The token has one longest completion: append it, and a space after a finished file name."""

    suffix: str

    def apply(self, editor: CompletingEditor, working_directory: Path, tokens: list[str], after: str) -> None:
        tokens = [*tokens[:-1], tokens[-1] + self.suffix]
        spacing = " " if (working_directory / tokens[-1]).is_file() else ""
        editor.replace_text(" ".join(token.replace(" ", "\\ ") for token in tokens) + after + spacing)


@dataclass(frozen=True)
class PathOptions(PathCompletion):
    """Several entries match, or none: the editor offers them."""

    options: tuple[str, ...]

    def apply(self, editor: CompletingEditor, working_directory: Path, tokens: list[str], after: str) -> None:
        editor.offer(list(self.options))


class PathComplete:
    """Auto completes paths."""

    def __init__(self) -> None:
        self.read_tasks: dict[Path, DirectoryReadTask] = {}
        self.directory_listings: dict[Path, list[Path]] = {}

    @classmethod
    def decorate_listing(cls, paths: Iterable[Path]) -> list[str]:
        """Add trailing slash to directories.

        Args:
            paths: A sequence of paths.

        Returns:
            A list of directory names.
        """
        return [(path.name + "/" if path.is_dir() else path.name) for path in paths]

    @classmethod
    def decorate_path(cls, path: Path) -> str:
        """Add trailing slash to a path if it is a directory.

        Args:
            path: Path.

        Returns:
            The path name, potentially with a trailing slash.
        """
        return path.name + "/" if path.is_dir() else path.name

    async def __call__(
        self,
        current_working_directory: Path,
        path: str,
        *,
        kinds: PathKinds = AnyPath(),
    ) -> PathCompletion:
        """Attempt to auto-complete a path.

        Args:
            current_working_directory: Current working directory (to resolve relative paths).
            path: String potentially containing path to auto-complete.
            kinds: Which entries may be offered.

        Returns:
            What the Tab press does: extend the token, or offer the matching options.
        """

        current_working_directory = (
            current_working_directory.expanduser().resolve().absolute()
        )
        directory_path = (current_working_directory / Path(path).expanduser()).resolve()

        node: str = path
        if not directory_path.is_dir():
            node = directory_path.name
            directory_path = directory_path.parent

        if (listing := self.directory_listings.get(directory_path)) is None:
            read_task = DirectoryReadTask(directory_path)
            self.read_tasks[directory_path] = read_task
            read_task.start()
            listing = await read_task.wait()

        def check_completions(
            listing: list[Path],
        ) -> PathCompletion:
            """Check completions from a listing (run in a thread)

            Args:
                listing: List of paths.

            Returns:
                Completions.
            """
            listing = [listing_path for listing_path in listing if kinds.keeps(listing_path)]

            if not node:
                return PathOptions(tuple(self.decorate_listing(listing)))

            node_name = Path(node).name

            if not node_name or path.endswith("/"):
                return PathOptions(tuple(self.decorate_listing(listing)))
            matching_nodes = [
                listing_path
                for listing_path in listing
                if listing_path.name.startswith(node_name)
            ]

            if not (matching_nodes):
                # Nothing matches
                return PathOptions(())

            if not (
                prefix := longest_common_prefix(
                    [node_path.name for node_path in matching_nodes]
                )
            ):
                return PathOptions(())

            picked_path = directory_path / prefix

            complete_name = Path(path).name
            completed_prefix = prefix[len(complete_name) :]
            path_options = [
                (
                    matched_path.name[len(complete_name) :] + "/"
                    if matched_path.is_dir()
                    else matched_path.name[len(complete_name) :]
                )
                for matched_path in matching_nodes
                if matched_path.name.startswith(complete_name)
            ]

            if len(path_options) > 1:
                return PathOptions(tuple(path_options))

            if picked_path.is_dir() and len(path_options) <= 1:
                completed_prefix += os.sep

            if completed_prefix:
                return ExtendedPath(completed_prefix)
            return PathOptions(tuple(path_options))

        return await asyncio.to_thread(check_completions, listing)


if __name__ == "__main__":

    async def run():
        path_complete = PathComplete()
        cwd = Path("~/sandbox")

        print(await path_complete(cwd, "~/p"))

    asyncio.run(run())
