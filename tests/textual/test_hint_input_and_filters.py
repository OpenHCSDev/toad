"""Real hint labels reach text entry and the sidebar's native control effects."""
from textual.widgets import Checkbox
from textual.widgets._collapsible import CollapsibleTitle
from textual.widgets._hints import HintLabel, HintSession

from toad.widgets.side_bar import SideBar, SideBarCollapsible
from toad.widgets.sidebar_tree import SidebarDisclosure, SidebarGroup
from toad.widgets.thread_comms import ThreadCommsSidebar
from toad.widgets.prompt import Prompt


async def test_hints_reach_search_editor_disclosures_and_message_filters(workspace):
    workspace.thread('hint-peer', 'hints')
    async with workspace.app(size=(160, 55)) as ui:
        app, _pilot = ui.textual
        editor = ui.conversation.prompt.prompt_text_area
        await ui.write_draft('keep this draft')
        left = app.screen.query_one('#channels-sidebar', SideBar)
        right = app.selected_session.query_one('#thread-sidebar', SideBar)
        left.reveal()
        right.reveal()
        await left.wait_content_ready()
        await right.wait_content_ready()
        tree = right.query_one(ThreadCommsSidebar)
        panel = tree.query_ancestor(SideBarCollapsible)
        panel.collapsed = False
        await ui.step()

        async def choose(widget):
            await ui.until(lambda: any(target.widget is widget for target in
                                      app.screen._compositor.activation_targets()),
                           why=f'{widget} to be an exposed published hint target')
            await app.screen.action_show_hints()
            await ui.step()
            labels = [label for label in app.screen.query_children(HintLabel)
                      if label.target.widget is widget and label.display]
            assert len(labels) == 1, (widget, labels)
            await ui.press(*labels[0].text)
            await ui.until(lambda: not app.screen.query_children(HintSession),
                           why='the chosen hint to retire')
            await ui.step()

        await choose(left.search_input)
        assert left.search_input.has_focus
        await ui.press(*'hints')
        assert left.search_input.value == 'hints'
        await choose(editor)
        assert editor.has_focus and editor.text == 'keep this draft'
        await choose(left.search_input)
        assert left.search_input.value == 'hints'
        left.search_input.value = ''
        editor.focus()
        await ui.step()

        title = panel.query_one(CollapsibleTitle)
        await choose(title)
        assert panel.collapsed and editor.has_focus
        await choose(title)
        assert not panel.collapsed and editor.has_focus

        checkbox = tree.query_one('.message-filter', Checkbox)
        category = tree._filter_controls[checkbox]
        before = ui.conversation.visible_categories
        await choose(checkbox)
        assert (category in ui.conversation.visible_categories) != (category in before)
        assert editor.has_focus and editor.text == 'keep this draft'
        await choose(checkbox)
        assert ui.conversation.visible_categories == before

        disclosure = next(control for control in app.screen.query(SidebarDisclosure)
                          if control.visible and control.region.height and control.region.width)
        group = disclosure.query_ancestor(SidebarGroup)
        expanded = group.expanded
        await choose(disclosure)
        assert group.expanded != expanded
        assert editor.has_focus and editor.text == 'keep this draft'
        await ui.open_channel('#hints', actor=workspace.viewer)
        await ui.write_draft('keep channel draft too')
        channel_editor = app.selected_session.query_one(Prompt).prompt_text_area
        await choose(left.search_input)
        await choose(channel_editor)
        assert channel_editor.has_focus and channel_editor.text == 'keep channel draft too'
        assert editor.text == 'keep this draft'
        assert ui.failure() is None
