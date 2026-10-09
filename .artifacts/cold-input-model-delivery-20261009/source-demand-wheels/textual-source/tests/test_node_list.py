import gc
from weakref import ref
from unittest.mock import patch

import pytest

from textual._node_list import DuplicateIds, NodeList
from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widget import Widget
from textual.widgets import Static


def test_empty_list():
    """Does an empty node list report as being empty?"""
    assert len(NodeList()) == 0


async def test_add_one():
    """Does adding a node to the node list report as having one item?"""
    nodes = NodeList()
    nodes._append(Widget())
    assert len(nodes) == 1


async def test_length_hint():
    """Check length hint dunder method."""
    nodes = NodeList()
    assert nodes.__length_hint__() == 0
    nodes._append(Widget())
    nodes._append(Widget())
    nodes._append(Widget())
    assert nodes.__length_hint__() == 3


async def test_repeat_add_one():
    """Does adding the same item to the node list ignore the additional adds?"""
    nodes = NodeList()
    widget = Widget()
    for _ in range(1000):
        nodes._append(widget)
    assert len(nodes) == 1


async def test_insert():
    nodes = NodeList()
    widget1 = Widget()
    widget2 = Widget()
    widget3 = Widget()
    nodes._append(widget1)
    nodes._append(widget3)
    nodes._insert(1, widget2)
    assert list(nodes) == [widget1, widget2, widget3]


async def test_truthy():
    """Does a node list act as a truthy object?"""
    nodes = NodeList()
    assert not bool(nodes)
    nodes._append(Widget())
    assert bool(nodes)


async def test_contains():
    """Can we check if a widget is (not) within the list?"""
    widget = Widget()
    nodes = NodeList()
    assert widget not in nodes
    nodes._append(widget)
    assert widget in nodes
    assert Widget() not in nodes


async def test_index():
    """Can we get the index of a widget in the list?"""
    widget = Widget()
    nodes = NodeList()
    with pytest.raises(ValueError):
        _ = nodes.index(widget)
    nodes._append(widget)
    assert nodes.index(widget) == 0


async def test_remove():
    """Can we remove a widget we've added?"""
    widget = Widget()
    nodes = NodeList()
    nodes._append(widget)
    assert widget in nodes
    nodes._remove(widget)
    assert widget not in nodes


@pytest.mark.parametrize("clear", [False, True])
async def test_removed_nodes_are_not_retained_by_unread_projection_caches(clear):
    nodes = NodeList()
    widget = Widget()
    weak_widget = ref(widget)
    nodes._append(widget)
    assert list(nodes.displayed) == [widget]
    assert list(nodes.displayed_and_visible) == [widget]
    if clear:
        nodes._clear()
    else:
        nodes._remove(widget)
    # Never read the projections again: invalidation must release their values,
    # not merely promise to replace them if a future traversal occurs.
    del widget
    gc.collect()
    assert weak_widget() is None


async def test_clear():
    """Can we clear the list?"""
    nodes = NodeList()
    assert len(nodes) == 0
    widgets = [Widget() for _ in range(1000)]
    for widget in widgets:
        nodes._append(widget)
    assert len(nodes) == 1000
    for widget in widgets:
        assert widget in nodes
    nodes._clear()
    assert len(nodes) == 0
    for widget in widgets:
        assert widget not in nodes


async def test_listy():
    nodes = NodeList()
    widget1 = Widget()
    widget2 = Widget()
    nodes._append(widget1)
    nodes._append(widget2)
    assert list(nodes) == [widget1, widget2]
    assert list(reversed(nodes)) == [widget2, widget1]
    assert nodes[0] == widget1
    assert nodes[1] == widget2
    assert nodes[0:2] == [widget1, widget2]


async def test_visible_children_do_not_replace_displayed_children():
    """Invisible children still occupy layout space after selection queries."""
    visible = Widget()
    invisible = Widget()
    invisible.styles.visibility = "hidden"
    nodes = NodeList()
    nodes._append(visible)
    nodes._append(invisible)
    assert list(nodes.displayed_and_visible) == [visible]
    assert list(nodes.displayed) == [visible, invisible]


async def test_visible_child_cache_tracks_inheritance_overrides_and_remount():
    class Counted(Static):
        visibility_reads = 0

        @property
        def visible(self) -> bool:
            self.visibility_reads += 1
            return super().visible

    class VisibilityApp(App):
        def compose(self) -> ComposeResult:
            with Container(id="outer"):
                with Container(id="inner"):
                    yield Counted("inherited", id="inherited")
                    yield Counted("explicit", id="explicit")

    app = VisibilityApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        outer = app.query_one("#outer")
        inner = app.query_one("#inner")
        inherited = app.query_one("#inherited", Counted)
        explicit = app.query_one("#explicit", Counted)
        explicit.styles.visibility = "visible"

        def check(expected):
            assert list(inner.displayed_and_visible_children) == expected
            assert list(inner.displayed_children) == list(inner.children)

        check([inherited, explicit])
        reads = inherited.visibility_reads, explicit.visibility_reads
        check([inherited, explicit])
        assert (inherited.visibility_reads, explicit.visibility_reads) == reads
        outer.styles.visibility = "hidden"
        check([explicit])
        outer.styles.visibility = None
        check([inherited, explicit])
        inherited.styles.visibility = "hidden"
        check([explicit])
        inherited.styles.visibility = None
        check([inherited, explicit])
        await inherited.remove()
        check([explicit])
        await inner.mount(inherited)
        check([explicit, inherited])
        explicit.display = False
        assert list(inner.displayed_and_visible_children) == [inherited]
        explicit.display = True
        check([explicit, inherited])


@pytest.mark.parametrize("insert", [False, True])
def test_duplicate_id_declines_custody_before_mutation(insert):
    parent = Widget()
    original = Widget(id="original")
    parent._add_child(original)
    with pytest.raises(DuplicateIds):
        if insert:
            parent._nodes._insert(0, Widget(id="original"))
        else:
            parent._nodes._append(Widget(id="original"))
    assert list(parent.children) == [original]
    assert parent.descendant_count == 1


async def test_native_cardinality_follows_custody_not_style_or_virtual_parent():
    class CustodyApp(App):
        def compose(self) -> ComposeResult:
            with Container(id="left"):
                yield Container(Static("one"), Static("two"), id="branch")
                yield Static("sibling", id="sibling")
            with Container(id="right"):
                yield Static("other")

    app = CustodyApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        left, right = app.query_one("#left"), app.query_one("#right")
        branch = app.query_one("#branch")

        def check(root=app.screen):
            # Independent traversal witnesses actual custody at each native
            # owner, including structure pending asynchronous removal.
            for node in root.walk_children(with_self=True):
                assert node.descendant_count == len(node.walk_children())

        check()
        original_count = app.screen.descendant_count
        branch.display = False
        branch.styles.visibility = "hidden"
        generation = left._nodes._updates
        with patch.object(left, "_child_nodes_removed", wraps=left._child_nodes_removed) as release:
            left.move_child(branch, after=left.children[-1])
            release.assert_not_called()
        assert left._nodes._updates == generation + 1
        generation = left._nodes._updates
        positions = {node: index for index, node in enumerate(left.children)}
        with patch.object(left, "refresh", wraps=left.refresh) as refresh:
            left.move_child(branch, after=left.children[0])
            left.sort_children(key=positions.__getitem__)
            refresh.assert_not_called()
        assert left._nodes._updates == generation
        await pilot.pause()
        assert app.screen.descendant_count == original_count
        check()

        pending = Container(Static("new one"), Static("new two"))
        assert pending.descendant_count == 0  # Composition has not acquired custody.
        await left.mount(pending, before=branch)
        check()
        branch.reparent(right)
        check()
        await pilot.pause()
        check()

        cover = Container(Static("virtual child"))
        left._cover(cover)
        await pilot.pause()
        assert cover.descendant_count == 1
        check(cover)
        check()  # A message parent without NodeList membership is not custody.
        left._uncover()
        await pilot.pause()
        check()

        await pending.remove()
        check()
        await right.remove_children()
        assert right.descendant_count == 0
        check()
        assert app._exception is None
