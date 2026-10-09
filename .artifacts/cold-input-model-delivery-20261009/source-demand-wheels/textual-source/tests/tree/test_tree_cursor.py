from __future__ import annotations

from typing import Any

import pytest

from textual import on
from textual.app import App, ComposeResult
from textual.widgets import Tree
from textual.widgets.tree import NodeID, TreeNode


class TreeApp(App[None]):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.messages: list[tuple[str, NodeID]] = []

    def compose(self) -> ComposeResult:
        tree = Tree[str](label="tree")
        self._node = tree.root.add_leaf("leaf")
        tree.root.expand()
        yield tree

    @property
    def node(self) -> TreeNode[str]:
        return self._node

    @on(Tree.NodeHighlighted)
    @on(Tree.NodeSelected)
    @on(Tree.NodeCollapsed)
    @on(Tree.NodeExpanded)
    def record_event(
        self,
        event: (
            Tree.NodeHighlighted[str]
            | Tree.NodeSelected[str]
            | Tree.NodeCollapsed[str]
            | Tree.NodeExpanded[str]
        ),
    ) -> None:
        self.messages.append((event.__class__.__name__, event.node.id))


async def test_move_cursor() -> None:
    """Test moving the cursor to a node (updating the highlighted node)."""
    async with TreeApp().run_test() as pilot:
        app = pilot.app
        tree: Tree[str] = app.query_one(Tree)
        node_to_move_to = app.node
        tree.move_cursor(node_to_move_to)
        await pilot.pause()

        # Note there are no Selected messages. We only move the cursor.
        assert app.messages == [
            ("NodeExpanded", 0),  # From the call to `tree.root.expand()` in compose
            ("NodeHighlighted", 0),  # From the initial highlight of the root node
            ("NodeHighlighted", 1),  # From the call to `tree.move_cursor`
        ]


async def test_move_cursor_reset() -> None:
    async with TreeApp().run_test() as pilot:
        app = pilot.app
        tree: Tree[str] = app.query_one(Tree)
        tree.move_cursor(app.node)
        tree.move_cursor(None)
        await pilot.pause()
        assert app.messages == [
            ("NodeExpanded", 0),  # From the call to `tree.root.expand()` in compose
            ("NodeHighlighted", 0),  # From the initial highlight of the root node
            ("NodeHighlighted", 1),  # From the 1st call to `tree.move_cursor`
            ("NodeHighlighted", 0),  # From the call to `tree.move_cursor(None)`
        ]


async def test_select_node() -> None:
    async with TreeApp().run_test() as pilot:
        app = pilot.app
        tree: Tree[str] = app.query_one(Tree)
        tree.select_node(app.node)
        await pilot.pause()
        assert app.messages == [
            ("NodeExpanded", 0),  # From the call to `tree.root.expand()` in compose
            ("NodeHighlighted", 0),  # From the initial highlight of the root node
            ("NodeHighlighted", 1),  # From the `tree.select_node` call
            ("NodeSelected", 1),  # From the call to `tree.select_node`
        ]


async def test_select_node_reset() -> None:
    async with TreeApp().run_test() as pilot:
        app = pilot.app
        tree: Tree[str] = app.query_one(Tree)
        tree.move_cursor(app.node)
        tree.select_node(None)
        await pilot.pause()

        # Notice no Selected messages.
        assert app.messages == [
            ("NodeExpanded", 0),  # From the call to `tree.root.expand()` in compose
            ("NodeHighlighted", 0),  # From the initial highlight of the root node
            ("NodeHighlighted", 1),  # From the `tree.move_cursor` call
            ("NodeHighlighted", 0),  # From the call to `tree.select_node(None)`
        ]


@pytest.mark.parametrize("operation", ["move", "select", "line", "scroll"])
async def test_unbuilt_offscreen_node(operation: str) -> None:
    """A mounted source mutation precedes rendering; intent must use its new line."""
    async with TreeApp().run_test(size=(40, 8)) as pilot:
        tree = pilot.app.query_one(Tree)
        for index in range(30):
            target = tree.root.add_leaf(str(index))
        assert target._line == -1
        assert tree._tree_lines_cached is None
        if operation == "move":
            tree.move_cursor(target)
        elif operation == "select":
            tree.select_node(target)
        elif operation == "line":
            tree.cursor_line = target.line
        else:
            tree.scroll_to_node(target, animate=False)
        assert target._line == 31
        if operation != "scroll":
            assert tree.cursor_node is target
        await pilot.pause()
        if operation != "line":
            assert tree.scroll_y > 0
        assert pilot.app._exception is None


@pytest.mark.parametrize("action", ["cursor_up", "cursor_down", "page_up", "page_down"])
async def test_navigation_after_lazy_line_rebase(action: str) -> None:
    """Navigation starts at the selected node's rebuilt line, not its old ordinal."""
    async with TreeApp().run_test(size=(40, 8)) as pilot:
        tree = pilot.app.query_one(Tree)
        nodes = [tree.root.add_leaf(str(index)) for index in range(30)]
        tree.move_cursor(nodes[15])
        old_line = tree.cursor_line
        tree.root.add_leaf("inserted", before=nodes[0])
        assert tree._tree_lines_cached is None
        step = tree.scrollable_content_region.height - 1
        offset = {
            "cursor_up": -1,
            "cursor_down": 1,
            "page_up": -step,
            "page_down": step,
        }[action]
        getattr(tree, "action_" + action)()
        assert tree.cursor_line == old_line + 1 + offset
        assert tree.cursor_node is nodes[15 + offset]
        assert pilot.app._exception is None


async def test_move_to_line_after_lazy_rebase() -> None:
    """The equality shortcut must compare the new projection's cursor ordinal."""
    async with TreeApp().run_test() as pilot:
        tree = pilot.app.query_one(Tree)
        target = pilot.app.node
        tree.move_cursor(target)
        previous_line = tree.cursor_line
        inserted = tree.root.add_leaf("inserted", before=target)
        tree.move_cursor_to_line(previous_line)
        assert tree.cursor_node is inserted
        assert pilot.app._exception is None


async def test_remount_restores_original_node_data() -> None:
    """Replacing the native Tree preserves external selection without a frame wait."""
    async with TreeApp().run_test() as pilot:
        tree = pilot.app.query_one(Tree)
        original_data = object()
        await tree.remove()
        replacement = Tree("replacement")
        target = replacement.root.add_leaf("selected", data=original_data)
        replacement.root.expand()
        await pilot.app.screen.mount(replacement)
        replacement.root.add_leaf("new source")
        replacement.move_cursor(target)
        assert replacement.cursor_node is target
        assert replacement.cursor_node.data is original_data
        assert replacement.get_node_at_line(replacement.cursor_line) is target
        assert pilot.app._exception is None


async def test_hidden_and_foreign_node_contract() -> None:
    """Projection acquisition does not reveal branches or acquire another Tree."""
    async with TreeApp().run_test() as pilot:
        tree = pilot.app.query_one(Tree)
        branch = tree.root.add("closed")
        hidden = branch.add_leaf("hidden")
        tree.move_cursor(hidden)
        assert tree.cursor_node is tree.root
        assert branch.is_collapsed
        assert hidden._line == -1
        unrelated = Tree("unrelated")
        foreign = unrelated.root.add_leaf("foreign")
        tree.move_cursor(foreign)
        assert tree.cursor_node is tree.root
        assert unrelated._tree_lines_cached is None
        tree.move_cursor(None)
        assert tree.cursor_node is tree.root
        tree.unselect()
        assert tree.cursor_line == -1
        assert tree.cursor_node is tree.root
