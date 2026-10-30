"""The real context panel keeps mounted navigation and rebinds detail after tree retirement."""

from toad.widgets.context_explorer import ContextExplorer, ContextTree
from toad.widgets.side_bar import SideBar, SideBarCollapsible

from support.overlapping_annotations import overlapping_annotations


async def test_tree_rebinds_corrections_and_remounts_on_the_same_row_without_a_new_selection(workspace):
    found = overlapping_annotations(workspace.project)
    spans, labels, inspection, short, long = found.spans, found.labels, found.inspection, found.short, found.long
    groups = found.refined_groups
    async with workspace.app(size=(120, 45)) as ui:
        app = ui.textual[0]
        sidebar = app.screen.query_one("#thread-sidebar", SideBar)
        sidebar.reveal()
        await sidebar.wait_content_ready()
        next(panel for panel in sidebar.query(SideBarCollapsible) if panel.title == "Context").collapsed = False
        explorer = sidebar.query_one(ContextExplorer)
        await ui.step()
        tree = explorer.query_one(ContextTree)
        tree.styles.height = 3
        tree.styles.min_height = 0
        intent = explorer.intent
        intent.selected = short
        tree.present(inspection.working_memory())
        short_node, long_node = tree.resolve_reader(short.key), tree.resolve_reader(long.key)
        tree.root.expand_all()
        await ui.step()
        tree.move_cursor(short_node, animate=False)
        await ui.step()
        assert short_node is not long_node
        assert tree.owns_node(short_node) and tree.owns_node(long_node)
        assert tree.cursor_node is short_node and intent.selected is short_node.data
        assert short_node.data.annotation.span == spans[0]
        assert long_node.data.annotation.span == spans[1]

        # Rebinding selected detail is not another native navigation request.
        tree.scroll_home(animate=False)
        await ui.step()
        assert short_node.line >= tree.scrollable_content_region.height
        reader_offset = tree.scroll_offset
        tree.present(inspection.working_memory())
        await ui.step()
        assert tree.cursor_node is short_node
        assert tree.scroll_offset == reader_offset
        assert intent.selected is short_node.data

        tree.present(groups)
        await ui.step()
        short_node, long_node = tree.resolve_reader(short.key), tree.resolve_reader(long.key)
        assert tree.owns_node(short_node) and tree.owns_node(long_node)
        assert tree.cursor_node is short_node and intent.selected is short_node.data
        assert short_node.data.annotation == found.corrected
        assert long_node.data.annotation == labels[1]

        await tree.remove()
        restored = ContextTree(explorer._show_detail, explorer._show_placeholder)
        await explorer.mount(restored)
        restored.present(groups)
        await ui.step()
        short_node, long_node = restored.resolve_reader(short.key), restored.resolve_reader(long.key)
        assert restored.owns_node(short_node) and restored.owns_node(long_node)
        # Detail intent survives. Retired native nodes do not own a new cursor.
        assert intent.selected is short_node.data
        assert restored.cursor_node is not short_node
        assert short_node.data.annotation == found.corrected and long_node.data.annotation == labels[1]
    assert app._exception is None
