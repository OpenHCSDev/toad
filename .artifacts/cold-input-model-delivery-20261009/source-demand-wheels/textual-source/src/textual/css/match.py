from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

from textual.css.model import SelectorSet

if TYPE_CHECKING:
    from textual.dom import DOMNode


def match(selector_sets: Iterable[SelectorSet], node: DOMNode) -> bool:
    """Check if a given node matches any of the given selector sets.

    Args:
        selector_sets: Iterable of selector sets.
        node: DOM node.

    Returns:
        True if the node matches the selector, otherwise False.
    """
    return any(selector_set.check(node) for selector_set in selector_sets)
