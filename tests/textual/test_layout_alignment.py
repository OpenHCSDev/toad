"""Textual-facing: the compositor places the channels sidebar, tab header and conversation edge to edge in the first frame, for collapsed and expanded sidebars, across sessions and resizes."""

from toad.widgets.session_tabs import SessionsTabs
from toad.widgets.side_bar import SideBar, TabHistoryControls

WIDTH, HEIGHT = 120, 44


def assert_aligned(ui, expected: int | None = None) -> None:
    screen = ui.app.screen
    left = screen.query_one("#channels-sidebar", SideBar)
    tabs = screen.query_one(SessionsTabs)
    conversation = ui.conversation
    assert conversation.region.x == left.region.right, (
        tabs.region, conversation.region, left.region, left.collapsed, left.styles.width,
        screen.query_one("#tab-navigation-header").styles.padding)
    if expected is not None:
        assert left.region.width == expected, (left.region, expected)
    else:
        assert 18 <= left.region.width <= screen.size.width // 2
    controls = screen.query_one(TabHistoryControls)
    assert (controls.region.x == 0 and tabs.region.x == controls.region.right
            and tabs.region.right == screen.region.right), (tabs.region, controls.region, screen.region)


async def test_sidebar_and_tab_header_stay_aligned_across_toggles_resizes_and_sessions(workspace):
    workspace.thread(workspace.project.name, running=True)
    expanded = WIDTH * 40 // 100
    async with workspace.app(size=(WIDTH, HEIGHT)) as ui:
        screen = ui.app.screen
        first = ui.selected_tab
        assert_aligned(ui, expanded)  # First visible frame, not a follow-up sidebar tick.
        await ui.resize(76, HEIGHT)
        assert_aligned(ui, 76 * 40 // 100)
        await ui.resize(WIDTH, HEIGHT)
        assert_aligned(ui, expanded)
        await ui.write_draft("retain draft")
        first_right = ui.app.selected_session.query_one("#thread-sidebar", SideBar)
        assert first_right.collapsed
        first_right.toggle()
        await ui.step()
        assert not first_right.collapsed
        assert_aligned(ui)

        left = screen.query_one("#channels-sidebar", SideBar)
        left.toggle()
        await ui.step()
        assert left.collapsed
        assert_aligned(ui, 3)
        left.toggle()
        await ui.step()
        assert_aligned(ui)
        left.toggle()
        await ui.step()
        assert_aligned(ui, 3)

        second = await ui.new_session()
        assert second != first
        assert_aligned(ui, 3)
        assert ui.app.selected_session.query_one("#thread-sidebar", SideBar).collapsed
        assert not first_right.collapsed  # The right sidebar belongs to its session.

        await ui.select_tab(first)
        assert_aligned(ui, 3)  # No stale header padding on the first frame after the switch.
        assert ui.draft() == "retain draft"
        screen.query_one("#channels-sidebar", SideBar).toggle()
        await ui.step()
        assert_aligned(ui)
        await ui.select_tab(second)
        assert_aligned(ui, expanded)
        assert ui.app.selected_session.query_one("#thread-sidebar", SideBar).collapsed
        await ui.select_tab(first)
        assert_aligned(ui)
