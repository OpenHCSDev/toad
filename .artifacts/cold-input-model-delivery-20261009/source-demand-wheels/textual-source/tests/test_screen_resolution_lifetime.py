from weakref import ref

import pytest

from textual.dom import DOMNode, NoScreen
from textual.screen import Screen


def test_cached_screen_follows_subtree_moves_and_detach():
    first, second = Screen(), Screen()
    branch, leaf = DOMNode(), DOMNode()
    branch._parent = first
    leaf._parent = branch
    assert leaf.screen is first
    assert leaf.screen is first
    branch._parent = second
    assert leaf.screen is second
    branch._parent = None
    with pytest.raises(NoScreen):
        leaf.screen


def test_screen_resolution_does_not_keep_ancestors_alive():
    screen = Screen()
    branch, leaf = DOMNode(), DOMNode()
    branch._parent = screen
    leaf._parent = branch
    assert leaf.screen is screen
    ancestor = ref(branch)
    del branch
    assert ancestor() is None
    with pytest.raises(NoScreen):
        leaf.screen


def test_cached_root_is_non_owning():
    screen, leaf = Screen(), DOMNode()
    leaf._parent = screen
    assert leaf.screen is screen
    root = ref(screen)
    del screen
    assert root() is None
    with pytest.raises(NoScreen):
        leaf.screen
