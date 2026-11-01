"""Textual-facing: pointer toggles preserve editor/footer resources; keyboard toggles enter the pane."""

from textual.widgets import Footer
from toad.sidebar_layout import SidebarPlacement
from toad.widgets.side_bar import SideBarToggle


async def test_pointer_toggles_keep_editing_focus_and_keyboard_toggle_enters_the_pane(workspace):
    async with workspace.app(size=(113, 42)) as ui:
        app, pilot = ui.textual
        prompt = ui.conversation.prompt.prompt_text_area
        await ui.write_draft("retained draft")
        bars = app.workspace_chrome.presented_sidebars()
        assert {bar.placement_identity for bar in bars} == set(SidebarPlacement.members_with(SidebarPlacement))
        for bar in bars:
            toggle = bar.toggle_control
            prompt.focus()
            await ui.step()
            footer = app.screen.query_one(Footer)
            footer_children = tuple(footer.walk_children())
            for _ in range(4):
                before = bar.collapsed
                assert await pilot.click(toggle)
                await ui.step()
                assert bar.collapsed != before
                assert app.focused is prompt, (bar.placement_identity, type(app.focused).__name__)
                assert ui.draft() == "retained draft"
                assert app.screen.query_one(Footer) is footer
                assert tuple(footer.walk_children()) == footer_children
            # Focus remains available for users reaching the handle by Tab.
            if not bar.collapsed:
                bar.toggle()
                await ui.step()
            toggle.focus(scroll_visible=False)
            await ui.step()
            await ui.press("enter")
            assert not bar.collapsed
            title = bar.query_one("SideBarCollapsible CollapsibleTitle")
            assert app.focused is title
            # Exercise native focus selection, not an overridden property that
            # deliberately sends Textual down its foreign-chain path.
            assert await pilot.click(toggle)
            await ui.step()
            assert bar.collapsed and app.focused is prompt
            assert ui.draft() == "retained draft"
