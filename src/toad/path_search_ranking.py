"""One path-scoring owner for every result size and catalog revision."""
import asyncio
from dataclasses import dataclass
from typing import Sequence

from textual.cache import LRUCache

from toad._path_fuzzy_search import PathFuzzySearch
from toad.fuzzy_index import FuzzyIndex


@dataclass(frozen=True)
class PathMatchQuery:
    text: str
    candidates: tuple[str, ...]


@dataclass(frozen=True)
class PathMatch:
    score: float
    offsets: Sequence[int]
    path: str


class PathSearchRanking:
    """Own the index, scorer and cache; a captured candidate set is cache identity."""

    def __init__(self) -> None:
        self.index = FuzzyIndex()
        self.scorer = PathFuzzySearch(case_sensitive=False)
        self.cache: LRUCache[PathMatchQuery, list[PathMatch]] = LRUCache(1024)

    async def update_paths(self, paths: list[str]) -> None:
        await self.index.update_paths(paths)
        self.cache.clear()

    async def search(self, text: str) -> list[PathMatch]:
        query = PathMatchQuery(text, tuple(await self.index.search(text)))
        if (scores := self.cache.get(query)) is None:
            scores = await asyncio.to_thread(self.score, query)
            self.cache[query] = scores
        return scores

    def score(self, query: PathMatchQuery) -> list[PathMatch]:
        matches = [PathMatch(*self.scorer.match(query.text, path), path) for path in query.candidates]
        return sorted((match for match in matches if match.score), key=lambda match: match.score, reverse=True)
