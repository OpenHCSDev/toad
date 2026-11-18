"""A path search over a project's paths, with no toolkit: Textual's PathSearch (the @
completion and its file picker) and Qt's QtPathSearch inherit it and draw what it answers.

The listing is what git does not ignore under the root, each path spelled relative to it (a
directory with a trailing slash), shallow paths first, and ranked against what was typed
by `PathSearchRanking`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from toad import directory
from toad.path_filter import PathFilter
from toad.path_search_ranking import PathSearchRanking


class ProjectPathSearch:
    """One project root's listing and its ranking. A plain mixin: Textual's widget
    metaclass refuses an ABC base and Qt's shiboken metaclass clashes with one."""

    root: Path
    ranking: PathSearchRanking
    path_filter: PathFilter | None = None

    def start_path_search(self, root: Path) -> None:
        self.root = root
        self.ranking = PathSearchRanking()

    async def scan_paths(self, *, add_directories: bool) -> list[Path]:
        """Every path git does not ignore under the root, absolute."""
        root = self.root
        self.path_filter = await asyncio.to_thread(PathFilter.from_git_root, root)
        paths = await directory.scan(root, path_filter=self.path_filter, add_directories=add_directories)
        return await asyncio.to_thread(lambda: [path.absolute() for path in paths])

    def spell_paths(self, paths: list[Path]) -> list[str]:
        """Each path relative to the root, a directory with a trailing slash, shallow first."""
        spellings = sorted(
            (str(path.relative_to(self.root)) + ("/" if path.is_dir() else "") for path in paths),
            key=str.lower)
        spellings.sort(key=lambda spelling: spelling.count("/"))
        return spellings

    async def rank_paths(self, spellings: list[str]) -> None:
        """Rank these spellings from now on."""
        await self.ranking.update_paths(spellings)

    async def ranked(self, text: str) -> list[str]:
        return [match.path for match in await self.ranking.search(text)]
