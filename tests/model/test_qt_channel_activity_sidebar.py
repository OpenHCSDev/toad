"""`ChannelActivitySidebar` reuses the shared `ChannelTreeSidebar` widget scoped to one channel."""

from __future__ import annotations

import os
from types import SimpleNamespace
from weakref import WeakSet

from agent_comms.display_order import LastActivityThreadSort
from agent_comms.messaging.channel_targets import ChannelTarget
from agent_comms.registry.thread_identity import RecordedThreadIncarnation
from agent_comms.registry.thread_model import UndeclaredModel
from agent_comms.registry.thread_presentation import IdleThreadPresentationStatus, WorkingThreadPresentationStatus
from agent_comms.ui_model.sidebar import ChannelRowModel, SidebarModel, ThreadRowModel
from agent_comms.ui_model.unread import ExactUnread
from pyqt_reactive.theming import ColorScheme
from PySide6.QtWidgets import QApplication
from ui_theme.clock import AnimationClock
from ui_theme.scheme import AccentColour

from toad.client.conversation import ChannelConversation
from toad.client.sidebar_state import Current
from toad.qt.theme import offered_schemes
from toad.qt.window import (
    ChannelActivitySidebar,
    ChannelTreeSidebar,
    SelectedChannelLine,
    Sidebar,
    ThreadLine,
)
from toad.setting_choices import ShownUnreadCount


def _thread_row(name: str, *, working: bool = False) -> ThreadRowModel:
    status = WorkingThreadPresentationStatus() if working else IdleThreadPresentationStatus()
    return ThreadRowModel(
        incarnation=RecordedThreadIncarnation(name=name, created_at=1.0),
        title=name,
        label=name,
        summary="working" if working else "idle",
        status=status,
        model=UndeclaredModel(),
        unread=ExactUnread(0),
        active=True,
    )


def _channel_row(name: str, members: tuple[str, ...], *, working: int = 0) -> ChannelRowModel:
    return ChannelRowModel(
        name=name,
        pinned=False,
        active_agents=len(members),
        registered_agents=len(members),
        tags=(),
        unread=ExactUnread(0),
        working_agents=working,
        members=members,
        pinned_members=frozenset(),
        order=LastActivityThreadSort,
    )


def test_channel_activity_sidebar_reuses_sidebar_tree_for_selected_channel(monkeypatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    qapp = QApplication.instance() or QApplication([])

    sidebar_model = SidebarModel(lambda fn: fn())
    sidebar_model.threads.rows = {
        "comms-a": _thread_row("comms-a", working=True),
        "toad-qt": _thread_row("toad-qt", working=False),
        "other-agent": _thread_row("other-agent", working=False),
    }
    sidebar_model.channels.rows = {
        "#comms": _channel_row("#comms", ("comms-a", "toad-qt"), working=1),
        "#other": _channel_row("#other", ("other-agent",), working=0),
    }

    class _Observed:
        sidebar = sidebar_model

        def show_sidebar(self, view) -> None:
            view.bind_observation(self)

    observed = _Observed()
    left: list[object] = []
    sidebar_views: WeakSet = WeakSet()
    access = SimpleNamespace(
        sidebar_views=sidebar_views,
        observation=SimpleNamespace(observed=lambda: observed),
        leave_sidebar=lambda view: (sidebar_views.discard(view), left.append(view)),
        update_sidebar_interest=lambda: None,
    )

    scheme = next(iter(offered_schemes(os.environ).values()))
    color_scheme = ColorScheme()

    class _Renderer:
        def themed(self, _widget, apply_fn) -> None:
            apply_fn()

        def theme(self, colour_type) -> str:
            return colour_type.rgb(scheme).hex

    opened: list[object] = []
    window = SimpleNamespace(
        renderer=_Renderer(),
        theme=SimpleNamespace(color_scheme=color_scheme),
        settings=SimpleNamespace(sidebar=SimpleNamespace(unread_counts=ShownUnreadCount)),
        thread_actions=SimpleNamespace(pending={}),
        animation_clock=AnimationClock(lambda _interval, _cb: lambda: None),
        coordination_access=access,
        open_row=lambda row: opened.append(row),
    )

    assert issubclass(ChannelActivitySidebar, ChannelTreeSidebar)
    assert issubclass(Sidebar, ChannelTreeSidebar)

    conversation = ChannelConversation(ChannelTarget("#comms"))
    bar = ChannelActivitySidebar(window, conversation)  # type: ignore[arg-type]

    # Bind + initial sync draws ONLY #comms (not #other, not NewSessionRow).
    assert isinstance(bar.model_state, Current)
    assert bar.topLevelItemCount() == 1
    channel_item = bar.topLevelItem(0)
    assert isinstance(channel_item, SelectedChannelLine)
    assert channel_item.key == "#comms"
    assert "#comms" in bar.groups and "#other" not in bar.groups
    assert bar.itemWidget(channel_item, 0) is channel_item.header

    # Starts collapsed at 1-row height; tapping the channel row expands its member TreeLines.
    assert not channel_item.isExpanded()
    collapsed_height = bar.height()
    assert collapsed_height > 0

    assert channel_item.childCount() == 2
    member_rows = [channel_item.child(i) for i in range(channel_item.childCount())]
    assert all(isinstance(row, ThreadLine) for row in member_rows)
    assert [row.key for row in member_rows] == ["comms-a", "toad-qt"]

    channel_item.activate(window)  # type: ignore[arg-type]
    assert channel_item.isExpanded()
    assert bar.height() > collapsed_height

    # Tapping a member opens that thread; tapping the channel row again collapses back.
    member_rows[0].activate(window)  # type: ignore[arg-type]
    assert opened == [member_rows[0]]

    channel_item.activate(window)  # type: ignore[arg-type]
    assert not channel_item.isExpanded()
    assert bar.height() == collapsed_height

    # Live incremental member change updates only #comms and keeps the SelectedChannelLine item.
    sidebar_model.threads.replace({
        **sidebar_model.threads.rows,
        "new-agent": _thread_row("new-agent", working=False),
    })
    sidebar_model.channels.replace({
        **sidebar_model.channels.rows,
        "#comms": _channel_row("#comms", ("comms-a", "toad-qt", "new-agent"), working=1),
    })
    sidebar_model.threads.flush()
    sidebar_model.channels.flush()
    assert bar.topLevelItem(0) is channel_item
    assert [channel_item.child(i).key for i in range(channel_item.childCount())] == [
        "comms-a",
        "toad-qt",
        "new-agent",
    ]

    # Cleanup removes from coordination_access.sidebar_views and retires waves.
    assert bar.selectionMode() == bar.SelectionMode.NoSelection
    assert bar.selectedItems() == []
    bar.close_activity()
    assert bar not in sidebar_views
    assert left == [bar]
    bar.close()
    qapp.processEvents()


def test_qt_history_window_inherits_reader_placement_jump_to_latest() -> None:
    from toad.client.history_pager import ReaderPlacement
    from toad.qt.history import QtHistoryWindow

    assert QtHistoryWindow.jump_to_latest is ReaderPlacement.jump_to_latest
