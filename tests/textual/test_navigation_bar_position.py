"""The navigation bar (menu, history arrows and tabs) sits above or below the conversation row, as its setting says, both when the setting changes and when Toad opens with it."""

import pytest

from toad.preferences import SETTINGS
from toad.setting_choices import NavigationBarPosition
from toad.widgets.comms_menu import ContextMenuOptions
from toad.widgets.side_bar import MainMenuButton
from toad.workspace_chrome import WorkspaceBody


def regions(app):
    return app.workspace_chrome.navigation.region, app.screen.query_one(WorkspaceBody).region


def placed(position, navigation, body) -> bool:
    """The member's own order, checked against the laid-out regions."""
    upper, lower = position.around(navigation, body)
    return upper.bottom <= lower.y


@pytest.mark.parametrize("position", NavigationBarPosition.members_with(NavigationBarPosition))
async def test_the_navigation_bar_moves_when_its_setting_changes_and_opens_where_it_was_left(workspace, position):
    async with workspace.app(size=(120, 40)) as ui:
        app, pilot = ui.textual
        for moved in (*NavigationBarPosition.members_with(NavigationBarPosition), position):
            app.saved_settings.set(SETTINGS.ui.navigation_bar, moved)
            await ui.step()
            navigation, body = regions(app)
            assert placed(moved, navigation, body), (moved, navigation, body)
        # Leaving the settings screen saves; the next Toad composes from the saved file.
        await app.saved_settings.save()
    async with workspace.app(size=(120, 40)) as ui:
        app, pilot = ui.textual
        await ui.step()
        navigation, body = regions(app)
        assert app.settings.ui.navigation_bar is position
        assert placed(position, navigation, body), (position, navigation, body)


@pytest.mark.parametrize("position", NavigationBarPosition.members_with(NavigationBarPosition))
async def test_the_main_menu_opens_toward_the_conversation_without_covering_its_button(workspace, position):
    async with workspace.app(size=(120, 32)) as ui:
        app, pilot = ui.textual
        app.saved_settings.set(SETTINGS.ui.navigation_bar, position)
        await ui.step()
        button = app.screen.query_one(MainMenuButton)
        button.open_menu()
        await ui.step()
        menu = app.screen.query_one(ContextMenuOptions).region
        # The conversation side of the button: below a top bar, above a bottom one.
        assert placed(position, button.region, menu), (position, button.region, menu)
