"""Members both frontends answered alike are answered by the parent they share.

Each pair here was reported by NominalRefactorAdvisor's `sibling_override` detector on
2026-11-20: two leaf classes overriding one inherited member with the same declaration.
"""

from __future__ import annotations


def _owned_by(owner: type, member: str, *leaves: type) -> None:
    for leaf in leaves:
        assert member not in vars(leaf), (leaf, member)
        assert getattr(leaf, member) is getattr(owner, member), (leaf, member)


def test_a_sidebar_grip_is_the_gesture_control_on_both_frontends():
    from toad.qt.side_bar import QtSidebarResizeHandle, QtSideBarToggle
    from toad.sidebar_layout import SidebarFoldGrip, SidebarResizeGrip
    from toad.widgets.side_bar import SidebarResizeHandle, SideBarToggle

    for member in ("drag_to", "dragged", "clicked"):
        _owned_by(SidebarResizeGrip, member, SidebarResizeHandle, SideBarToggle, QtSidebarResizeHandle, QtSideBarToggle)
    # The toggle's click folds the pane; the handle's shows its controls.
    for toggle in (SideBarToggle, QtSideBarToggle):
        assert toggle.grip_clicked is SidebarFoldGrip.grip_clicked


def test_a_transfer_form_names_its_request_and_each_dialog_family_finds_its_member():
    from toad.client.transfer_forms import ThreadImportForm, WireExportForm
    from toad.client.transfers import ThreadImportRequest, WireExportRequest
    from toad.qt.transfer import QtThreadImportDialog, QtTransferDialog, QtWireExportDialog
    from toad.widgets.comms_transfer import ThreadImportDialog, TransferDialog, WireExportDialog

    _owned_by(WireExportForm, "request_kind", WireExportDialog, QtWireExportDialog)
    _owned_by(ThreadImportForm, "request_kind", ThreadImportDialog, QtThreadImportDialog)
    assert TransferDialog.for_kind(WireExportRequest) is WireExportDialog
    assert TransferDialog.for_kind(ThreadImportRequest) is ThreadImportDialog
    assert QtTransferDialog.for_kind(WireExportRequest) is QtWireExportDialog
    assert QtTransferDialog.for_kind(ThreadImportRequest) is QtThreadImportDialog


def test_a_location_with_nothing_to_show_says_so_once():
    from toad.client.reader_position import FragmentLocation, UnloadedFragment
    from toad.qt.history import QtRowLocation

    for member in ("tooltip", "selected_by", "bodies"):
        _owned_by(FragmentLocation, member, UnloadedFragment, QtRowLocation)


def test_settings_agentless_presentation_and_source_refresh_are_the_shared_owners():
    from toad.client.history import ReadMarkedHistory
    from toad.client.view_settings import SettingsReading, ViewSettingsOwner
    from toad.launch_binding import AgentConversation
    from toad.qt.acp_tab import QtAcpSessionView
    from toad.qt.conversation import QtConversation
    from toad.qt.history import QtConversationHistory, QtHistoryWindow
    from toad.qt.prompt_stack import QtInfoBar, QtSettingVisibility, QtStatusLine
    from toad.qt.settings_screen import QtSettingsScreen
    from toad.screens.settings import SettingsScreen
    from toad.settings_editing import SettingsEditing
    from toad.settings_scope import SettingsReader
    from toad.widgets.conversation import Conversation
    from toad.widgets.wire_history import WireHistory

    _owned_by(ViewSettingsOwner, "configuration_settings", QtConversation)
    _owned_by(AgentConversation, "present_without_agent", Conversation, QtAcpSessionView)
    _owned_by(ReadMarkedHistory, "refresh_source", WireHistory, QtConversationHistory)
    _owned_by(SettingsEditing, "edited_settings", SettingsScreen, QtSettingsScreen)
    # Reading the settings of the view a widget sits in is one parent; Textual finds the
    # view among its ancestors, a Qt widget is handed it.
    for reader in (SettingsReader, QtStatusLine, QtInfoBar, QtHistoryWindow):
        _owned_by(SettingsReading, "configuration_state", reader)
    for row in (QtStatusLine, QtInfoBar):
        _owned_by(QtSettingVisibility, "show_setting", row)
        _owned_by(QtSettingVisibility, "showEvent", row)


def test_flash_coordination_held_rows_and_live_revision_are_the_shared_owners():
    from toad.client.bus_selection import BusListing
    from toad.client.fragments import GrowsInPlace
    from toad.client.prompt_stack import FlashNotice
    from toad.qt.agent_surface import QtLiveToolFragment
    from toad.qt.bus_switcher import QtBusSwitcher
    from toad.qt.live_turn import QtLiveFragment
    from toad.qt.prompt_stack import QtFlash, QtSessionDetails
    from toad.screens.bus_choice import ListsBuses
    from toad.status_thread import ObservedActivity
    from toad.widgets.flash import Flash
    from toad.widgets.observed_thread_activity import ObservedThreadActivity

    _owned_by(FlashNotice, "settings", Flash, QtFlash)
    _owned_by(ObservedActivity, "coordination", ObservedThreadActivity, QtSessionDetails)
    _owned_by(BusListing, "held_rows", ListsBuses, QtBusSwitcher)
    _owned_by(GrowsInPlace, "revision", QtLiveFragment, QtLiveToolFragment)
    # The counter, not the event count, keys a live row.
    assert QtLiveFragment(events=(), live_revision=3).revision == 3


def test_the_surface_a_view_lends_its_agent_holds_the_view_weakly_on_both_frontends():
    from toad.agent_surface import AttachedSurfaceBinding
    from toad.qt.agent_surface import QtSurfaceBinding
    from toad.surface_binding import ViewSurfaceBinding

    for member in ("target", "sync_queue", "close"):
        _owned_by(ViewSurfaceBinding, member, AttachedSurfaceBinding, QtSurfaceBinding)

    class View:
        retired = None

        def retire_core(self, subscription) -> None:
            self.retired = subscription

    class Subscription:
        closed = False

        def close(self) -> None:
            self.closed = True

    class Lent(ViewSurfaceBinding):
        def post(self, message) -> bool:
            return False

    view, subscription, surface = View(), Subscription(), Lent()
    surface.lend(view, subscription)
    assert surface.target is view and surface.owns(view)
    surface.close()
    assert view.retired is subscription and not subscription.closed
    # A view that is gone is no target; closing then releases the subscription itself.
    del view
    assert surface.target is None
    surface.close()
    assert subscription.closed


def test_a_view_with_nothing_to_wait_for_retire_or_reload_inherits_that_and_its_origin():
    from toad.client.session_scope import NoSessionOrigin, SessionScope
    from toad.qt.acp_tab import QtAcpSessionView
    from toad.qt.mailbox_view import QtMailboxView
    from toad.qt.opening_view import QtOpeningSessionView
    from toad.qt.page import Page
    from toad.qt.window import ConversationView
    from toad.screens.session_view import SessionView

    _owned_by(SessionScope, "wait_content_ready", QtMailboxView, QtOpeningSessionView, SessionView)
    _owned_by(SessionScope, "retire_presentation", QtMailboxView, QtOpeningSessionView)
    _owned_by(SessionScope, "origin", QtMailboxView, QtAcpSessionView, ConversationView)
    _owned_by(Page, "reload", QtMailboxView, QtOpeningSessionView, QtAcpSessionView)

    class Channel(SessionScope):
        mode = "comms:#scratch"

    origin = Channel().origin
    assert isinstance(origin, NoSessionOrigin) and origin.view == "comms:#scratch"


def test_the_qt_agent_tab_is_a_session_scope_as_the_mailbox_view_is():
    """Navigation asks every view it opens to take a load plan, wait for its content and
    retire its presentation; the Qt agent tab answered none of them."""
    from toad.client.session_scope import BoundSources, SessionScope
    from toad.qt.acp_tab import QtAcpSessionView
    from toad.qt.mailbox_view import QtMailboxView

    for view in (QtAcpSessionView, QtMailboxView):
        assert issubclass(view, BoundSources)
        assert view.apply_native_load_plan is BoundSources.apply_native_load_plan
        assert view.wait_content_ready is SessionScope.wait_content_ready
        assert view.retire_presentation is SessionScope.retire_presentation


def test_the_qt_thread_views_share_their_column_scope_wave_and_queue_rows():
    from toad.client.project_view import ProjectView
    from toad.qt.acp_tab import QtAcpSessionView
    from toad.qt.agent_surface import QtSurfaceBinding
    from toad.qt.mailbox_view import QtMailboxView
    from toad.qt.name_wave import QtClockedWave, QtTabWave
    from toad.qt.project_panel import QtProjectPanel
    from toad.qt.queue_ui import QtOpensQueue, QtQueueHint, QtQueueSummary
    from toad.qt.thread_view import QtThreadView
    from toad.qt.window import ConversationRow
    from toad.surface_binding import SurfaceBinding

    for member in ("_lay_out_thread", "transcript_scope", "identity_line", "thread_activity", "goal_bar"):
        _owned_by(QtThreadView, member, QtAcpSessionView, QtMailboxView)
    for member in ("permission_changed", "prepare_terminal"):
        _owned_by(SurfaceBinding, member, QtSurfaceBinding)
    _owned_by(ProjectView, "refresh_if_visible", QtProjectPanel)
    for member in ("wave_running", "start_wave", "stop_wave"):
        _owned_by(QtClockedWave, member, QtTabWave, ConversationRow)
    _owned_by(QtOpensQueue, "activate", QtQueueSummary, QtQueueHint)
