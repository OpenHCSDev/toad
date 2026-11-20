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
