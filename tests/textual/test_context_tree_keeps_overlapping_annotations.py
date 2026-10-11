"""Textual-facing: the context tree (a Textual Tree widget) selects, scrolls and remounts overlapping annotations without losing the reader's row or position."""

from textual.app import App
from toad.textual_colours import ThemedApp
from toad.widgets.context_explorer import ContextTree, ContextTreeIntent

from support.overlapping_annotations import overlapping_annotations


class TreeApp(ThemedApp, App):
    def __init__(self, tree):
        super().__init__()
        self.subject = tree

    def compose(self):
        yield self.subject


async def test_tree_rebinds_corrections_and_remounts_on_the_same_row_without_a_new_selection(tmp_path):
    found = overlapping_annotations(tmp_path)
    spans, labels, inspection, short, long = found.spans, found.labels, found.inspection, found.short, found.long
    groups = found.refined_groups
    intent = ContextTreeIntent(selected=short)
    detail = []
    tree = ContextTree(intent, detail.append, lambda text: None)
    tree.styles.height = 3
    app = TreeApp(tree)
    async with app.run_test() as pilot:
        tree.present(inspection.working_memory())
        await pilot.pause()
        short_node, long_node = tree.reveal(short.key), tree.reveal(long.key)
        assert short_node is not long_node
        assert tree.owns_node(short_node) and tree.owns_node(long_node)
        assert tree.cursor_node is short_node and intent.selected is short_node.data
        assert short_node.data.annotation.span == spans[0]
        assert long_node.data.annotation.span == spans[1]

        # A wheel scroll can leave the selected native row outside the
        # viewport. Rebinding its source is not a new navigation request.
        tree.scroll_home(animate=False)
        await pilot.pause()
        assert short_node.line >= tree.scrollable_content_region.height
        reader_offset = tree.scroll_offset
        detail.clear()
        tree.present(inspection.working_memory())
        await pilot.pause()
        assert tree.cursor_node is short_node
        assert tree.scroll_offset == reader_offset
        assert detail == [short_node.data]

        tree.present(groups)
        await pilot.pause()
        short_node, long_node = tree.reveal(short.key), tree.reveal(long.key)
        assert tree.owns_node(short_node) and tree.owns_node(long_node)
        assert tree.cursor_node is short_node and intent.selected is short_node.data
        assert short_node.data.annotation == found.corrected
        assert long_node.data.annotation == labels[1]
        assert detail[-1] is short_node.data

        await tree.remove()
        restored = ContextTree(intent, detail.append, lambda text: None)
        await app.mount(restored)
        restored.present(groups)
        await pilot.pause()
        short_node, long_node = restored.reveal(short.key), restored.reveal(long.key)
        assert restored.owns_node(short_node) and restored.owns_node(long_node)
        assert restored.cursor_node is short_node and intent.selected is short_node.data
        assert short_node.data.annotation == found.corrected and long_node.data.annotation == labels[1]
        assert detail[-1] is short_node.data
    assert app._exception is None
