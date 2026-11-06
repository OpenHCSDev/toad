"""Every Toad screen keeps the geometry its removed stylesheet declared (64430c0, "Toad has no CSS").

Each assertion is one rule that commit deleted: a panel's percentage size, the screen centring it,
and the 1fr child that takes the panel's remaining height above its docked or auto-height controls.
"""

from agent_comms.historical_views import HistoricalThread
from agent_comms.repo import Checkout
from agent_comms.registry.threads import NativeThread

from support.goals import published_goal
from support.roots import installed_wire
from toad.screens.goal_details import GoalDetails, GoalDetailsClose, GoalDetailsPanel, GoalDocument
from toad.screens.historical_sessions import HistoricalSessions
from toad.screens.keymap import KeymapPanel, KeymapScreen, KeymapStatus, KeymapTable
from toad.screens.modal import ModalPanel
from toad.screens.welcome import WelcomeColumn, WelcomeScreen
from toad.screens.queue import QueueActions, QueueInspection, QueuePanel
from toad.screens.team import HudRows, TeamClose, TeamPage, TeamPanel
from toad.widgets.history_anchor import HistoryWindow
from textual.containers import VerticalScroll

SIZE = WIDTH, HEIGHT = 100, 40


def assert_centred_panel(panel, width: int, height: int) -> None:
    """The panel has the removed rule's size, centred by the screen's removed `align: center middle`."""
    screen = panel.screen.region
    region = panel.region
    facts = {"panel": region, "screen": screen}
    assert (region.width, region.height) == (width, height), facts
    assert abs((region.x - screen.x) - (screen.right - region.right)) <= 1, facts
    assert abs((region.y - screen.y) - (screen.bottom - region.bottom)) <= 1, facts


def inner_bottom(panel) -> int:
    """The last row a panel's children may occupy: inside its border and padding."""
    return panel.content_region.bottom


async def test_team_page_is_a_centred_95_percent_panel_with_close_docked_under_the_rows(workspace):
    async with workspace.app(size=SIZE) as ui:
        page = TeamPage()
        await ui.app.push_screen(page)
        await ui.step()
        panel, rows, close = page.query_one(TeamPanel), page.query_one(HudRows), page.query_one(TeamClose)
        assert_centred_panel(panel, 95, 38)
        facts = {"panel": panel.content_region, "rows": rows.region, "close": close.region}
        assert close.region.bottom == inner_bottom(panel), facts
        assert rows.region.bottom == close.region.y, facts


async def test_saved_history_is_a_centred_95_percent_panel_its_window_fills(workspace):
    old, live = installed_wire(workspace.roots.attempt / "old"), workspace.comms
    for name in ("sender", "agent"):
        old.registry.declare(NativeThread(name, frozenset(), Checkout(workspace.project)))
    workspace.thread("agent")
    old.messaging.send("sender", "agent", "SAVED_GEOMETRY")
    source = live.views.attach_history(old.root)
    item = HistoricalThread(source, source.provenance.require("agent"))
    async with workspace.app(size=SIZE) as ui:
        screen = HistoricalSessions(live, (item,))
        await ui.app.push_screen(screen)
        await ui.until(lambda: "SAVED_GEOMETRY" in ui.painted(screen), why="the saved message")
        panel, window = screen.query_one(ModalPanel), screen.query_one(HistoryWindow)
        assert_centred_panel(panel, 95, 38)
        assert window.region.bottom == inner_bottom(panel), {"panel": panel.content_region, "window": window.region}


async def test_keymap_is_a_centred_95_percent_panel_its_table_fills(workspace):
    async with workspace.app(size=SIZE) as ui:
        ui.conversation.prompt.prompt_text_area.focus()
        await ui.step()
        await ui.press("f1")
        await ui.until(lambda: isinstance(ui.app.screen, KeymapScreen), why="the keymap menu")
        await ui.step()
        screen = ui.app.screen
        panel, table, status = screen.query_one(KeymapPanel), screen.query_one(KeymapTable), screen.query_one(KeymapStatus)
        assert_centred_panel(panel, 95, 38)
        facts = {"panel": panel.content_region, "table": table.region, "status": status.region}
        assert status.region.bottom == inner_bottom(panel), facts
        assert table.region.height > 3, facts


async def test_queue_details_are_a_centred_85_by_75_percent_panel_its_scroll_fills(workspace):
    async with workspace.app(size=SIZE) as ui:
        ui.conversation.open_queue_menu()
        await ui.until(lambda: isinstance(ui.app.screen, QueueInspection), why="the queue inspection screen")
        await ui.step()
        screen = ui.app.screen
        panel, scroll, actions = screen.query_one(QueuePanel), screen.query_one(VerticalScroll), screen.query_one(QueueActions)
        assert_centred_panel(panel, 85, 30)
        facts = {"panel": panel.content_region, "scroll": scroll.region, "actions": actions.region}
        assert actions.region.bottom == inner_bottom(panel), facts
        assert scroll.region.height > 1, facts


async def test_goal_history_is_a_centred_95_percent_panel_with_close_docked_under_the_document(workspace):
    async with workspace.app(size=SIZE) as ui:
        ui.conversation.goal_display = published_goal("GEOMETRY_GOAL", "goal", progress="Progress.")
        await ui.until_shows("History")
        await ui.click("History")
        await ui.until(lambda: isinstance(ui.app.screen, GoalDetails), why="the goal details screen")
        await ui.step()
        screen = ui.app.screen
        panel, document, close = screen.query_one(GoalDetailsPanel), screen.query_one(GoalDocument), screen.query_one(GoalDetailsClose)
        assert_centred_panel(panel, 95, 38)
        facts = {"panel": panel.content_region, "document": document.region, "close": close.region}
        assert close.region.bottom == inner_bottom(panel), facts
        assert document.region.bottom < close.region.y, facts


async def test_welcome_column_is_64_wide_and_centred_beside_the_sidebar(workspace):
    async with workspace.app(size=(120, 40), session=False) as ui:
        await ui.until_shows("n new session")
        welcome = ui.app.screen.query_one(WelcomeScreen)
        column, sidebar = welcome.query_one(WelcomeColumn), ui.app.workspace_chrome.channels
        space, region = welcome.content_region, column.region
        facts = {"welcome": space, "column": region, "sidebar": sidebar.region}
        assert region.x >= sidebar.region.right, facts
        assert region.width == 64, facts
        assert abs((region.x - space.x) - (space.right - region.right)) <= 1, facts
        assert abs((region.y - space.y) - (space.bottom - region.bottom)) <= 1, facts
