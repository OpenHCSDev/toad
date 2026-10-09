from unittest.mock import patch

from textual.app import App
from textual.dom import DOMNode
from textual.widgets import Static


def test_style_only_nodes_do_not_allocate_unused_tree_or_query_storage():
    from textual._node_list import NodeList
    from textual.cache import LRUCache

    with patch("textual.dom.NodeList", wraps=NodeList) as nodes, \
            patch("textual.dom.LRUCache", wraps=LRUCache) as queries:
        component = DOMNode(classes="component")
        assert component.classes == frozenset({"component"})
        assert nodes.call_count == 0 and queries.call_count == 0
        assert list(component.children) == []
        assert nodes.call_count == 1 and queries.call_count == 0
        assert component.children is component.children
        assert component.query_one_optional("#missing") is None
        assert queries.call_count == 1


def test_lazily_created_collections_belong_to_each_node():
    first, second = DOMNode(), DOMNode()
    first._disabled_messages.add(str)
    assert not second._disabled_messages
    first._next_callbacks.append("first")
    assert not second._next_callbacks
    assert first._nodes is not second._nodes
    assert first.message_signal is not second.message_signal
    assert first.message_signal.owner is first
    assert second.message_signal.owner is second


async def test_component_selectors_and_parent_styles_still_work():
    class Badge(Static):
        COMPONENT_CLASSES = {"badge--text"}
        DEFAULT_CSS = "Badge > .badge--text { color: red; } Badge.hot > .badge--text { color: green; }"

    app = App()
    async with app.run_test() as pilot:
        badge = Badge("label")
        await app.mount(badge)
        await pilot.pause()
        assert badge.get_component_styles("badge--text").color.css == "rgb(255,0,0)"
        badge.add_class("hot")
        await pilot.pause()
        assert badge.get_component_styles("badge--text").color.css == "rgb(0,128,0)"
