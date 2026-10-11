"""Textual-facing: pointer clicks on a sidebar toggle keep focus in the editor (no handle focus, no footer rebuild); keyboard toggles still enter the pane."""

from unittest.mock import PropertyMock, patch

from textual.widgets import Footer
from toad.widgets.side_bar import SideBar, SideBarToggle


async def test_pointer_toggles_keep_editing_focus_and_keyboard_toggle_enters_the_pane(workspace):
    async with workspace.app(size=(113, 42)) as ui:
        app, pilot = ui.textual
        prompt = ui.conversation.prompt.prompt_text_area
        await ui.write_draft("retained draft")
        for identity in ("channels-sidebar", "thread-sidebar"):
            bar = app.selected_session.query_one(f"#{identity}", SideBar) if identity == "thread-sidebar" \
                else app.screen.query_one(f"#{identity}", SideBar)
            toggle = bar.query_one(SideBarToggle)
            prompt.focus()
            await ui.step()
            footer = app.screen.query_one(Footer)
            with patch.object(footer, "recompose", wraps=footer.recompose) as recompose:
                for _ in range(4):
                    before = bar.collapsed
                    assert await pilot.click(toggle)
                    await ui.step()
                    assert bar.collapsed != before
                    assert app.focused is prompt, (identity, type(app.focused).__name__)
                    assert ui.draft() == "retained draft"
                assert recompose.call_count == 0
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
            # Closing while focus is inside the pane returns it to input.
            with patch.object(type(app.screen), "focus_chain", new_callable=PropertyMock,
                              side_effect=AssertionError("Hidden pane rebuilt the full focus chain")):
                assert await pilot.click(toggle)
                await ui.step()
            assert bar.collapsed and app.focused is prompt
