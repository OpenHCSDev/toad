"""Textual-facing: the context tree (a Textual Tree widget) of overlapping annotations keeps the reader's row and
position when its source is refreshed, and keeps the selected annotation through a correction and a remount.

The mounted Tree owns navigation; the explorer's intent owns which annotation's detail is selected."""

from toad.widgets.context_explorer import ContextExplorer, ContextTree
from toad.widgets.side_bar import SideBarCollapsible, ThreadSidebar

from support.overlapping_annotations import overlapping_annotations


async def reveal_context(ui) -> ContextExplorer:
    """Open the session's Context panel and return its explorer."""
    sidebar = await ui.revealed(ui.app.screen.query_one(ThreadSidebar))
    explorer = sidebar.query_one(ContextExplorer)
    explorer.query_ancestor(SideBarCollapsible).collapsed = False
    await ui.step()
    return explorer


async def test_tree_rebinds_corrections_and_remounts_on_the_same_row_without_a_new_selection(workspace, tmp_path):
    found = overlapping_annotations(tmp_path)
    spans, labels, inspection, short, long = found.spans, found.labels, found.inspection, found.short, found.long
    groups = found.refined_groups
    async with workspace.app(size=(120, 40)) as ui:
        explorer = await reveal_context(ui)
        intent = explorer.intent
        tree = explorer.query_one(ContextTree)
        tree.styles.height = tree.styles.min_height = 3
        tree.present(inspection.working_memory())
        await ui.step()
        short_node, long_node = tree.resolve_reader(short.key), tree.resolve_reader(long.key)
        # The reader opens the rows above the short annotation and highlights it.
        opened = short_node.parent
        while opened is not None:
            opened.expand()
            opened = opened.parent
        await ui.step()
        tree.move_cursor(short_node, animate=False)
        await ui.step()
        assert short_node is not long_node
        assert tree.owns_node(short_node) and tree.owns_node(long_node)
        assert tree.cursor_node is short_node and intent.selected is short_node.data
        assert short_node.data.annotation.span == spans[0]
        assert long_node.data.annotation.span == spans[1]

        # A wheel scroll can leave the selected native row outside the
        # viewport. Rebinding its source is not a new navigation request.
        tree.scroll_home(animate=False)
        await ui.step()
        assert short_node.line >= tree.scrollable_content_region.height
        reader_offset = tree.scroll_offset
        tree.present(inspection.working_memory())
        await ui.step()
        assert tree.cursor_node is short_node
        assert tree.scroll_offset == reader_offset
        assert intent.selected is short_node.data

        # A correction moves the annotation to its corrected group; the selection follows it.
        tree.present(groups)
        await ui.step()
        short_node, long_node = tree.resolve_reader(short.key), tree.resolve_reader(long.key)
        assert tree.owns_node(short_node) and tree.owns_node(long_node)
        assert intent.selected is short_node.data
        assert short_node.data.annotation == found.corrected
        assert long_node.data.annotation == labels[1]

        # Eviction releases the panel widgets and keeps the panel's reader intent;
        # the explorer composed again for the same session restores the selection.
        sidebar = ui.app.screen.query_one(ThreadSidebar)
        await sidebar.evict(sidebar.screen)
        assert not explorer.is_attached
        # Showing the session again hydrates its panels, as a tab return does.
        await sidebar.prepare_presentation()
        restored = await reveal_context(ui)
        assert restored is not explorer
        tree = restored.query_one(ContextTree)
        tree.present(groups)
        await ui.step()
        short_node, long_node = tree.resolve_reader(short.key), tree.resolve_reader(long.key)
        assert tree.owns_node(short_node) and tree.owns_node(long_node)
        assert restored.intent is intent and intent.selected is short_node.data
        assert short_node.data.annotation == found.corrected and long_node.data.annotation == labels[1]
        assert ui.failure() is None
