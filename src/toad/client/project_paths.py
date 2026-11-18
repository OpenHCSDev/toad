"""A project's paths as the path search lists and ranks them, with no toolkit.

The @ completion and the file pickers search the same list: what git does not ignore under
the project root, each spelled relative to it (a directory with a trailing slash), shallow
paths first, and ranked against what was typed by `PathSearchRanking`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from toad import directory
from toad.path_filter import PathFilter
from toad.path_search_ranking import PathSearchRanking


class ProjectPaths:
    """One project root's listing and its ranking."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.ranking = PathSearchRanking()
        self.path_filter: PathFilter | None = None

    async def scan(self, *, add_directories: bool) -> list[Path]:
        """Every path git does not ignore, absolute."""
        self.path_filter = await asyncio.to_thread(PathFilter.from_git_root, self.root)
        paths = await directory.scan(self.root, path_filter=self.path_filter, add_directories=add_directories)
        return await asyncio.to_thread(lambda: [path.absolute() for path in paths])

    def spelled(self, paths: list[Path]) -> list[str]:
        """Each path relative to the root, a directory with a trailing slash, shallow first."""
        spellings = sorted(
            (str(path.relative_to(self.root)) + ("/" if path.is_dir() else "") for path in paths),
            key=str.lower)
        spellings.sort(key=lambda spelling: spelling.count("/"))
        return spellings

    async def listed(self, *, add_directories: bool) -> list[str]:
        """The spelled listing, ranked from now on by `search`."""
        spellings = await asyncio.to_thread(self.spelled, await self.scan(add_directories=add_directories))
        await self.ranking.update_paths(spellings)
        return spellings

    async def search(self, text: str) -> list[str]:
        return [match.path for match in await self.ranking.search(text)]
