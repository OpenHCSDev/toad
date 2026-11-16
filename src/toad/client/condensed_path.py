"""How a path is shown in a fixed width: home-relative, a trailing slash for a directory, and
condensed from the middle out so its root and its last parts stay readable."""

from functools import lru_cache
import os.path
from typing import Iterable

from rich.cells import cell_len
from rich.text import Text


def radiate_range(total: int) -> Iterable[tuple[int, int]]:
    """Generate pairs of indexes, gradually growing from the center.

    Args:
        total: Total size of range.

    Yields:
        Pairs of indexes.
    """
    if not total:
        return
    left = right = total // 2
    yield (left, right)
    while left >= 0 or right < total:
        left -= 1
        if left >= 0:
            yield (left + 1, right)
        right += 1
        if right <= total:
            yield (left + 1, right)


@lru_cache(maxsize=16)
def condense_path(path: str, width: int, *, prefix: str = "") -> str:
    """Condense a path to fit within the given cell width.

    Args:
        path: The path to condense.
        width: Maximum cell width.
        prefix: A string to be prepended to the result.

    Returns:
        A condensed string.
    """
    # TODO: handle OS separators and path issues
    if cell_len(path) <= width:
        return path
    components = path.split("/")
    condensed = components
    trailing_slash = path.endswith("/")
    candidate = prefix + "/".join(condensed)
    if trailing_slash and candidate and not candidate.endswith("/"):
        candidate += "/"

    for left, right in radiate_range(len(components)):
        if cell_len(candidate) <= width:
            return candidate
        condensed = [*components[:left], "…", *components[right:]]
        if len(condensed) <= 2:
            last = Text(components[-1])
            last.truncate(width, overflow="ellipsis")
            return last.plain
        candidate = prefix + "/".join(condensed)
        if trailing_slash and candidate and not candidate.endswith("/"):
            candidate += "/"

    return candidate


def home_relative(path: str, *, directory: bool = False) -> str:
    """The absolute path, written from ~/ when it is under the user's home; a directory
    ends in a slash."""
    path = os.path.abspath(os.path.expanduser(path))
    user_root = os.path.abspath(os.path.expanduser("~/"))
    if not user_root.endswith("/"):
        user_root += "/"
    if path.startswith(user_root):
        path = "~/" + path[len(user_root):]
    if directory and not path.endswith("/"):
        path += "/"
    return path
