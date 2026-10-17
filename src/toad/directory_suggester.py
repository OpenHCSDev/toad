import itertools
import threading
from pathlib import Path

from textual.cache import LRUCache
from textual.suggester import Suggester

from toad.work_preparation import PreparationRuntime


class ListDirCache:
    """A cache for listing a directory (not a Rich / Textual object).

    This class is responsible for listing directories, and caching the results.

    Listing a directory is a blocking operation, which is why we defer the work to a thread.

    """

    def __init__(self) -> None:
        self._cache: LRUCache[tuple[str, int], list[Path]] = LRUCache(100)
        self._lock = threading.Lock()

    def listdir(self, path: Path, size: int) -> list[Path]:
        cache_key = (str(path), size)
        with self._lock:
            if cache_key not in self._cache:
                self._cache[cache_key] = list(itertools.islice(path.iterdir(), size))
            return self._cache[cache_key]


class DirectorySuggester(Suggester):
    """Suggest a directory.

    This is a [Suggester](https://textual.textualize.io/api/suggester/#textual.suggester.Suggester) instance,
    used by the Input widget to suggest auto-completions.

    """

    def __init__(self, preparation: PreparationRuntime) -> None:
        self.preparation = preparation
        self._cache = ListDirCache()
        super().__init__(case_sensitive=True)

    async def get_suggestion(self, value: str) -> str | None:
        return await self.preparation.run_thread(self.suggest, value)

    def suggest(self, value: str) -> str | None:
        """Resolve the complete suggestion inside the accepted preparation work."""
        try:
            path = Path(value)
            name = path.name

            children = self._cache.listdir(
                path.expanduser() if path.is_dir() else path.parent.expanduser(), 100
            )
            possible_paths = [
                f"{sibling_path}/"
                for sibling_path in children
                if sibling_path.name.lower().startswith(name.lower())
                and sibling_path.is_dir()
            ]
            if possible_paths:
                possible_paths.sort(key=str.__len__)
                suggestion = possible_paths[0]

                if "~" in value:
                    home = str(Path("~").expanduser())
                    suggestion = suggestion.replace(home, "~", 1)
                return suggestion

        except FileNotFoundError:
            pass
        return None
