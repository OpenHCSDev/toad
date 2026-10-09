"""

Cache classes are dict-like containers used to avoid recalculating expensive operations such as rendering.

You can also use them in your own apps for similar reasons.

"""

from __future__ import annotations

from collections import OrderedDict
from typing import TYPE_CHECKING, Generic, KeysView, TypeVar, overload

CacheKey = TypeVar("CacheKey")
CacheValue = TypeVar("CacheValue")
DefaultValue = TypeVar("DefaultValue")
_MISSING = object()

__all__ = ["LRUCache", "FIFOCache"]


class LRUCache(Generic[CacheKey, CacheValue]):
    """
    A dictionary-like container with a maximum size.

    If an additional item is added when the LRUCache is full, the least
    recently used key is discarded to make room for the new item.

    The values dictionary preserves insertion-order key views. A C-backed
    OrderedDict owns recency without one cyclic Python list per cache entry.

    Note that stdlib's @lru_cache is implemented in C and faster! It's best to use
    @lru_cache where you are caching things that are fairly quick and called many times.
    Use LRUCache where you want increased flexibility and you are caching slow operations
    where the overhead of the cache is a small fraction of the total processing time.
    """

    __slots__ = [
        "_maxsize",
        "_cache",
        "_full",
        "_recency",
        "hits",
        "misses",
    ]

    def __init__(self, maxsize: int) -> None:
        """Initialize a LRUCache.

        Args:
            maxsize: Maximum size of the cache, before old items are discarded.
        """
        self._maxsize = maxsize
        self._cache: dict[CacheKey, CacheValue] = {}
        self._full = False
        self._recency: OrderedDict[CacheKey, None] = OrderedDict()
        self.hits = 0
        self.misses = 0
        super().__init__()

    @property
    def maxsize(self) -> int:
        """int: Maximum size of cache, before new values evict old values."""
        return self._maxsize

    @maxsize.setter
    def maxsize(self, maxsize: int) -> None:
        self._maxsize = maxsize

    def __bool__(self) -> bool:
        return bool(self._cache)

    def __len__(self) -> int:
        return len(self._cache)

    def __repr__(self) -> str:
        return f"<LRUCache size={len(self)} maxsize={self._maxsize} hits={self.hits} misses={self.misses}>"

    def grow(self, maxsize: int) -> None:
        """Grow the maximum size to at least `maxsize` elements.

        Args:
            maxsize: New maximum size.
        """
        self.maxsize = max(self.maxsize, maxsize)

    def clear(self) -> None:
        """Clear the cache."""
        self._cache.clear()
        self._full = False
        self._recency.clear()

    def keys(self) -> KeysView[CacheKey]:
        """Get cache keys."""
        # Mostly for tests
        return self._cache.keys()

    def set(self, key: CacheKey, value: CacheValue) -> None:
        """Set a value.

        Args:
            key: Key.
            value: Value.
        """
        if key not in self._cache:
            self._cache[key] = value
            self._recency[key] = None
            if self._full or len(self._cache) > self._maxsize:
                self._full = True
                oldest, _ = self._recency.popitem(last=False)
                del self._cache[oldest]

    __setitem__ = set

    if TYPE_CHECKING:

        @overload
        def get(self, key: CacheKey) -> CacheValue | None: ...

        @overload
        def get(
            self, key: CacheKey, default: DefaultValue
        ) -> CacheValue | DefaultValue: ...

    def get(
        self, key: CacheKey, default: DefaultValue | None = None
    ) -> CacheValue | DefaultValue | None:
        """Get a value from the cache, or return a default if the key is not present.

        Args:
            key: Key
            default: Default to return if key is not present.

        Returns:
            Either the value or a default.
        """

        value = self._cache.get(key, _MISSING)
        if value is _MISSING:
            self.misses += 1
            return default
        self._recency.move_to_end(key)
        self.hits += 1
        return value  # type: ignore[return-value]

    def __getitem__(self, key: CacheKey) -> CacheValue:
        value = self._cache.get(key, _MISSING)
        if value is _MISSING:
            self.misses += 1
            raise KeyError(key)
        self._recency.move_to_end(key)
        self.hits += 1
        return value  # type: ignore[return-value]

    def __contains__(self, key: CacheKey) -> bool:
        return key in self._cache

    def discard(self, key: CacheKey) -> None:
        """Discard item in cache from key.

        Args:
            key: Cache key.
        """
        if key not in self._cache:
            return
        del self._cache[key]
        del self._recency[key]
        self._full = False


class FIFOCache(Generic[CacheKey, CacheValue]):
    """A simple cache that discards the first added key when full (First In First Out).

    This has a lower overhead than LRUCache, but won't manage a working set as efficiently.
    It is most suitable for a cache with a relatively low maximum size that is not expected to
    do many lookups.

    """

    __slots__ = [
        "_maxsize",
        "_cache",
        "hits",
        "misses",
    ]

    def __init__(self, maxsize: int) -> None:
        """Initialize a FIFOCache.

        Args:
            maxsize: Maximum size of cache before discarding items.
        """
        self._maxsize = maxsize
        self._cache: dict[CacheKey, CacheValue] = {}
        self.hits = 0
        self.misses = 0

    def __bool__(self) -> bool:
        return bool(self._cache)

    def __len__(self) -> int:
        return len(self._cache)

    def __repr__(self) -> str:
        return (
            f"<FIFOCache maxsize={self._maxsize} hits={self.hits} misses={self.misses}>"
        )

    def clear(self) -> None:
        """Clear the cache."""
        self._cache.clear()

    def keys(self) -> KeysView[CacheKey]:
        """Get cache keys."""
        # Mostly for tests
        return self._cache.keys()

    def set(self, key: CacheKey, value: CacheValue) -> None:
        """Set a value.

        Args:
            key: Key.
            value: Value.
        """
        if key not in self._cache and len(self._cache) >= self._maxsize:
            for first_key in self._cache:
                self._cache.pop(first_key)
                break
        self._cache[key] = value

    __setitem__ = set

    if TYPE_CHECKING:

        @overload
        def get(self, key: CacheKey) -> CacheValue | None: ...

        @overload
        def get(
            self, key: CacheKey, default: DefaultValue
        ) -> CacheValue | DefaultValue: ...

    def get(
        self, key: CacheKey, default: DefaultValue | None = None
    ) -> CacheValue | DefaultValue | None:
        """Get a value from the cache, or return a default if the key is not present.

        Args:
            key: Key
            default: Default to return if key is not present.

        Returns:
            Either the value or a default.
        """
        try:
            result = self._cache[key]
        except KeyError:
            self.misses += 1
            return default
        else:
            self.hits += 1
            return result

    def __getitem__(self, key: CacheKey) -> CacheValue:
        try:
            result = self._cache[key]
        except KeyError:
            self.misses += 1
            raise KeyError(key) from None
        else:
            self.hits += 1
            return result

    def __contains__(self, key: CacheKey) -> bool:
        return key in self._cache
