"""Regression tests for the four comms-tui UX fixes:
1. Sidebar row name renders in primary foreground (white) and detail/state renders muted.
2. Clicking a read receipt link or MessageNotifications does not scroll back to message top.
3. Divider outside rules (`───`) and timestamp carry `rule_link` (`FragmentCollapse`), just
   like the arrow between names.
4. Revealing a message head updates `scroll_target_y` so scrolling up does not snap back to
   the bottom first.
"""

from __future__ import annotations

from types import SimpleNamespace

from rich.style import Style as RichStyle
from textual.content import Content
from textual.geometry import Offset
from textual.widgets import Static

from toad.client.fragments import FragmentCollapse, FragmentKey
from toad.client.line_blocks import AgentRole, Divider, OpenTarget, Span
from toad.message_rows import RecordedEventTime
from toad.native_style import MutedText
from toad.navigation_target import ThreadTarget
from toad.widgets.comms_sidebar import ThreadStatusRow
from toad.widgets.conversation import Conversation
from toad.widgets.message_notifications import MessageNotifications
from toad.widgets.transcript_lines import OpenLineLink, RichLineRenderer


def test_thread_status_row_drops_muted_text() -> None:
    assert MutedText not in ThreadStatusRow.__mro__


def test_conversation_on_click_ignores_link_clicks() -> None:
    selected: list[object] = []

    class _StubConv(Conversation):
        @property
        def is_current_session(self) -> bool:
            return True

        @property
        def screen(self):
            return SimpleNamespace(get_selected_text=lambda: "")

    stub = _StubConv.__new__(_StubConv)
    stub._mouse_down_offset = Offset(5, 5)
    stub.navigation = SimpleNamespace(select=lambda w: selected.append(w) or True)
    stub.refresh_block_cursor = lambda fn: selected.append("scrolled")

    link_event = SimpleNamespace(
        screen_offset=Offset(5, 5),
        widget=Static("receipt"),
        style=RichStyle(meta={"@click": OpenLineLink(FragmentCollapse(FragmentKey(source=1, part=0)))}),
    )
    stub.on_click(link_event)
    assert selected == []


async def test_comms_tui_ux_bar_colors_divider_rules_receipts_and_scroll(workspace) -> None:
    workspace.thread("source")
    async with workspace.app(size=(90, 30), resume="source") as ui:
        app, pilot = ui.textual

        # 1. Sidebar row name is brighter (primary foreground) than muted state/detail line.
        await ui.until(lambda: bool(app.screen.query(ThreadStatusRow)), why="sidebar thread row mounted")
        row = app.screen.query(ThreadStatusRow).first()
        await ui.step()
        name_strip = row.render_line(0, row._paint_state)
        state_strip = row.render_line(1, row._paint_state)
        name_fg = name_strip._segments[0].style.color
        state_fg = state_strip._segments[0].style.color
        assert name_fg != state_fg
        if name_fg and state_fg and name_fg.triplet and state_fg.triplet:
            assert sum(name_fg.triplet) > sum(state_fg.triplet)

        # 2. Clicking inside MessageNotifications never bubbles to Conversation scroll-to-top.
        feedback = MessageNotifications()
        await ui.conversation.mount(feedback)
        await ui.step()
        scrolled: list[object] = []
        original_refresh = ui.conversation.refresh_block_cursor
        ui.conversation.refresh_block_cursor = lambda fn: scrolled.append("scrolled")
        try:
            title = feedback.query_one("CollapsibleTitle")
            assert await pilot.click(title)
            await ui.step()
            assert not feedback.collapsed
            await pilot.click(feedback.details)
            await ui.step()
            assert scrolled == []
        finally:
            ui.conversation.refresh_block_cursor = original_refresh

        # 3. Divider outside rules (`───`) and timestamp carry `rule_link` (`FragmentCollapse`),
        #    while sender/target links keep `OpenTarget`.
        collapse = FragmentCollapse(FragmentKey(source=1, part=0))
        divider = Divider(
            spans=(
                Span("▼ ", AgentRole, collapse),
                Span("comms-a", AgentRole, OpenTarget("comms-a")),
                Span(" ──> ", AgentRole, collapse),
                Span("#comms", AgentRole, OpenTarget("#comms")),
            ),
            role=AgentRole,
            timestamp=RecordedEventTime(1_700_000_000.0),
            rule_link=collapse,
        )
        rows = RichLineRenderer(app.colours.line_theme, 80).rows((divider,))
        assert len(rows) == 1
        segments = rows[0]

        def click_of(substring: str) -> object | None:
            for seg in segments:
                if substring in seg.text:
                    return seg.style.meta.get("@click") if seg.style else None
            return None

        assert segments[0].text.startswith("─")
        assert segments[0].style.meta.get("@click") == OpenLineLink(collapse)
        assert segments[-1].text.endswith("─")
        assert segments[-1].style.meta.get("@click") == OpenLineLink(collapse)
        assert click_of("──>") == OpenLineLink(collapse)
        assert click_of("·") == OpenLineLink(collapse)
        assert click_of("comms-a") == OpenLineLink(OpenTarget("comms-a"))
        assert click_of("#comms") == OpenLineLink(OpenTarget("#comms"))

        # 4. Revealing a message head syncs `scroll_target_y` so scrolling up moves up from the
        #    head instead of snapping back to the bottom first.
        win = ui.conversation.window
        for i in range(60):
            await win.mount(Static(f"line {i}"))
        await ui.step()
        win.scroll_end(animate=False)
        await ui.step()
        bottom = win.scroll_y
        assert bottom > 20
        assert win.scroll_target_y == bottom

        target_y = max(5.0, bottom - 20.0)
        win.release_anchor()
        win.start_head_reveal(target_y)
        # If animations are enabled, drive to completion; if disabled, already at target_y.
        if win.head_reveal is not None:
            win.head_reveal.finish()
        await ui.step()
        assert win.scroll_y == target_y
        assert win.scroll_target_y == target_y

        win._scroll_up_for_pointer(animate=False)
        await ui.step()
        assert win.scroll_y < target_y
        assert win.scroll_target_y < target_y
