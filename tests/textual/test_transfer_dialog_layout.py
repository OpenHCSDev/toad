"""Both real transfer grammars retain fields while actions stay outside scrolling."""

import pytest
from textual.widgets import Button, Input, OptionList, Select
from support.workspace import Workspace

from toad.widgets.comms_transfer import Transfer


@pytest.mark.parametrize("transfer", Transfer.members_with(Transfer), ids=lambda kind: kind.declared_name)
@pytest.mark.parametrize("height", (20, 40))
async def test_transfer_actions_survive_short_viewport_and_notice(
    workspace: Workspace, transfer: type[Transfer], height: int,
) -> None:
    async with workspace.app(size=(110, height)) as ui:
        app, pilot = ui.textual
        access = app.coordination_access
        selected = access.selected(access.observation.observed().service.root)
        # Exercise the actual notification/layout mechanism, not a fake exporter
        # result. The separate physical06 evidence establishes real FileExistsError.
        app.notify("Existing destination was preserved. " * 8,
                   title="Transfer notice", severity="error", timeout=60)
        dialog = transfer.dialog(selected)
        app.push_screen(dialog)
        await ui.until(lambda: app.screen is dialog and bool(dialog.query(Input)),
                       why="the transfer's native fields")
        field = dialog.query(Input).first()
        field.value = "unsent field value"
        await pilot.resize_terminal(110, 20)
        await ui.until(lambda: dialog.query_one("#cancel-transfer", Button).region.height > 0,
                       why="the action row after resize")
        for identity in ("#submit-transfer", "#cancel-transfer"):
            button = dialog.query_one(identity, Button)
            geometry = app.screen.find_widget(button)
            assert geometry.visible_region == geometry.region
            x, y = geometry.region.center
            assert app.screen.get_widget_at(x, y)[0] is button
        for choice in dialog.query(Select):
            selected_value = choice.selection
            choice.focus()
            await ui.press("enter")
            await ui.until(lambda: choice.expanded, why="the native choice popup")
            popup = choice.query_one(OptionList)
            visible = app.screen.find_widget(popup).visible_region
            assert visible.area > 0
            assert app.screen.get_widget_at(*visible.center)[0] is popup
            await ui.press("escape")
            await ui.until(lambda: not choice.expanded, why="popup dismissal without closing its dialog")
            assert app.screen is dialog
            assert choice.selection == selected_value
        assert field.value == "unsent field value"
        await ui.press("escape")
        await ui.until(lambda: app.screen is not dialog, why="native dialog dismissal")
