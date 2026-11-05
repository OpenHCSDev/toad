"""Real hint labels reach text entry and the sidebar's native control effects."""
from toad.widgets.side_bar import ThreadSidebar
from toad.widgets.channels_sidebar import ChannelsSidebar
from textual.widgets._collapsible import CollapsibleTitle
from textual.widgets._hints import HintLabel, HintSession

from toad.widgets.side_bar import SideBar, SideBarCollapsible
from toad.widgets.comms_sidebar import ChannelHeaderRow
from toad.widgets.thread_comms import MessageFilter, ThreadCommsSidebar
from toad.widgets.prompt import Prompt


async def test_hints_reach_search_editor_disclosures_and_message_filters(workspace):
    workspace.thread('hint-peer', 'hints')
    async with workspace.app(size=(160, 55)) as ui:
        app, _pilot = ui.textual
        editor = ui.conversation.prompt.prompt_text_area
        await ui.write_draft('keep this draft')
        left = app.screen.query_one(ChannelsSidebar)
        right = app.selected_session.query_one(ThreadSidebar)
        left.reveal()
        right.reveal()
        await ui.panels_loaded(left)
        await ui.panels_loaded(right)
        tree = right.query_one(ThreadCommsSidebar)
        panel = tree.query_ancestor(SideBarCollapsible)
        panel.collapsed = False
        await ui.step()

        async def choose(widget):
            await choose_target(lambda target: target.widget is widget, widget)

        async def choose_target(matches, described):
            await ui.until(lambda: any(matches(target) for target in
                                      app.screen._compositor.activation_targets()),
                           why=f'{described} to be an exposed published hint target')
            await app.screen.action_show_hints()
            await ui.step()
            labels = [label for label in app.screen.query_children(HintLabel)
                      if matches(label.target) and label.display]
            assert len(labels) == 1, (described, labels)
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

        checkbox = tree.query_one(MessageFilter)
        category = tree._filter_controls[checkbox]
        before = ui.conversation.visible_categories
        await choose(checkbox)
        assert (category in ui.conversation.visible_categories) != (category in before)
        assert editor.has_focus and editor.text == 'keep this draft'
        await choose(checkbox)
        assert ui.conversation.visible_categories == before

        # A group's disclosure is a painted stretch of its header line, with a hint of its own.
        row = next(row for row in left.query(ChannelHeaderRow)
                   if row.visible and row.region.height and row.region.width)
        group = row.header_group
        disclosure = group.leading_segments[0]
        expanded = group.expanded
        await choose_target(lambda target: target.identity == (row, disclosure.activate), disclosure)
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
