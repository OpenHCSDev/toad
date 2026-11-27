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
    from toad.widgets.fragment_states import FragmentSpan

    for member in ("tooltip", "selected_by", "bodies"):
        _owned_by(FragmentLocation, member, UnloadedFragment, QtRowLocation)
    for member in ("location", "for_layout", "find_in"):
        _owned_by(FragmentLocation, member, QtRowLocation, FragmentSpan)


def test_hoisted_frontend_owners_for_mentions_sidebars_context_and_agent_turns():
    from toad.client.context_intent import ContextInspectionReader
    from toad.client.mention_completion import MentionEditor
    from toad.launch_binding import AgentConversation
    from toad.qt.acp_tab import QtAcpSessionView
    from toad.qt.composer import Composer
    from toad.qt.context_panel import QtContextExplorer
    from toad.qt.side_bar import QtSideBar
    from toad.sidebar_layout import SidebarSurface
    from toad.widgets.channel_prompt import ChannelPrompt
    from toad.widgets.context_explorer import ContextExplorer
    from toad.widgets.conversation import Conversation
    from toad.widgets.side_bar import SideBar

    _owned_by(MentionEditor, "set_mention_candidates", Composer, ChannelPrompt)
    _owned_by(SidebarSurface, "toggle_controls", QtSideBar, SideBar)
    for member in (
        "_inspection_acquired", "_run_native_read", "_native_acquired",
        "older_requests", "newer_requests", "_change_page",
    ):
        _owned_by(ContextInspectionReader, member, QtContextExplorer, ContextExplorer)
    for member in ("agent_turn_over", "submission_request_failed"):
        _owned_by(AgentConversation, member, QtAcpSessionView, Conversation)

    from toad.client.sort_control import SortControlBase
    from toad.qt.channel_sort import QtSortButton
    from toad.widgets.session_sort import SortChoice

    for member in ("visibility_fields", "visibility_toggle_label", "_toggle_visibility"):
        _owned_by(SortControlBase, member, QtSortButton, SortChoice)
    _owned_by(SortControlBase, "saved_settings", QtSortButton)

    # Exercise ContextInspectionReader._change_page directly through older_requests.
    events: list[tuple] = []

    class _FakeInspection:
        class page:
            older = "cursor-older"
            newer = "cursor-newer"

    class _FakeState:
        def present(self, fn):
            fn(type("_Holding", (), {"inspection": _FakeInspection()})())

    class _FakeIdentity:
        def inspection_state(self):
            return "fresh-state"

    class _ProbeReader(ContextInspectionReader):
        thread_identity = _FakeIdentity()

        def set_page_controls(self, *, older: bool, newer: bool) -> None:
            events.append(("controls", older, newer))

        def cancel_page_work(self) -> None:
            events.append(("cancel",))

        def clear_page_display(self, placeholder: str) -> None:
            events.append(("clear", placeholder))

        def reload_page(self) -> None:
            events.append(("reload",))

    reader = _ProbeReader()
    reader.start_inspection({})
    reader.state = _FakeState()
    reader.older_requests()
    assert reader.intent.cursor == "cursor-older"
    assert reader.state == "fresh-state"
    assert events == [
        ("cancel",),
        ("controls", False, False),
        ("clear", "Loading recorded request page…"),
        ("reload",),
    ]


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
    from toad.history_jump import FollowsTail
    from toad.widgets.history_anchor import HistoryWindow
    for member in ("rejoin_reached_tail", "record_reader_scroll"):
        _owned_by(FollowsTail, member, HistoryWindow, QtHistoryWindow)
    for row in (QtStatusLine, QtInfoBar):
        _owned_by(QtSettingVisibility, "show_setting", row)
        _owned_by(QtSettingVisibility, "showEvent", row)


def test_flash_coordination_held_rows_and_live_revision_are_the_shared_owners():
    from toad.client.bus_selection import BusListing
    from toad.client.fragments import GrowsInPlace
    from toad.flash_host import FlashNotice
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

    for member in ("target", "sync_queue", "close", "owns_publication", "present_tool", "present_permission"):
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

        async def show_tool_call(self, message, target, status) -> None:
            pass

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


def test_a_view_with_nothing_to_wait_for_or_retire_inherits_that_and_its_origin():
    from toad.client.session_sources import SourcedConversation
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
    _owned_by(Page, "reload", QtOpeningSessionView)
    _owned_by(SourcedConversation, "reload", QtMailboxView, QtAcpSessionView)

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

    for member in (
        "_lay_out_thread", "transcript_scope", "shown", "identity_line", "thread_activity", "goal_bar"
    ):
        _owned_by(QtThreadView, member, QtAcpSessionView, QtMailboxView)
    for member in ("permission_changed", "prepare_terminal"):
        _owned_by(SurfaceBinding, member, QtSurfaceBinding)
    _owned_by(ProjectView, "refresh_if_visible", QtProjectPanel)
    for member in ("wave_running", "start_wave", "stop_wave"):
        _owned_by(QtClockedWave, member, QtTabWave, ConversationRow)
    _owned_by(QtOpensQueue, "activate", QtQueueSummary, QtQueueHint)


def test_thread_sidebar_panel_family_owns_both_frontends_panels():
    from toad.qt.context_panel import QtContextExplorer
    from toad.qt.coordination_panel import QtCoordinationStatus
    from toad.qt.plan_panel import QtPlan
    from toad.qt.project_panel import QtProjectPanel
    from toad.qt.thread_comms_panel import QtThreadCommsPanel
    from toad.thread_sidebar_declarations import (
        CommsSidebarPanel,
        CoordinationSidebarPanel,
        DmSidebarPanel,
        ThreadSidebarPanel,
    )
    from toad.widgets.session_thread_panels import SessionPanel

    declared = tuple(ThreadSidebarPanel.members_with(ThreadSidebarPanel))
    assert tuple(ThreadSidebarPanel.members_with(DmSidebarPanel)) == (
        CoordinationSidebarPanel,
        CommsSidebarPanel,
    )
    qt_panels = (QtCoordinationStatus, QtThreadCommsPanel, QtPlan, QtProjectPanel, QtContextExplorer)
    assert tuple(panel.panel_type for panel in qt_panels) == declared
    assert tuple(panel.panel_type for panel in SessionPanel.members_with(SessionPanel)) == declared


def test_animates_arrivals_is_shared_by_both_history_windows():
    from contextlib import nullcontext
    from dataclasses import dataclass
    from ui_theme.clock import AnimationClock
    from toad.arrivals import AnimatesArrivals, ArrivalFadeRun, ArrivalGlide, HeadReveal
    from toad.qt.history import QtHistoryWindow
    from toad.widgets.history_anchor import HistoryWindow

    for member in (
        "arrive_fragments",
        "arrive",
        "glide_to_end",
        "gliding_to_end",
        "start_head_reveal",
        "head_reveal_travel",
        "shift_arrival_motion",
        "cancel_head_reveal",
        "cancel_arrival_glide",
        "stop_arrival_motion",
        "arrival_landed",
        "has_active_arrivals",
        "has_arrival",
        "arrival_keys",
        "arrival_frame",
        "arrival_opacity",
    ):
        _owned_by(AnimatesArrivals, member, HistoryWindow, QtHistoryWindow)

    @dataclass(frozen=True)
    class _Frag:
        key: str
        source_identity: str

    class _ProbeReader:
        def joins_tail(self, _window) -> bool:
            return True

    class _ProbeWindow(AnimatesArrivals):
        def __init__(self) -> None:
            self._clock = AnimationClock(lambda _dt: None)
            self.follows_tail = True
            self.scroll_y = 100.0
            self.tail_scroll_y = 140.0
            self.reader_position = _ProbeReader()
            self.repainted: list[tuple[object, ...]] = []

        @property
        def animation_clock(self) -> AnimationClock:
            return self._clock

        @property
        def arrival_animation_visible(self) -> bool:
            return True

        def layout_scroll(self):
            return nullcontext()

        def arrival_rows_height(self, keys: tuple[object, ...]) -> float | None:
            return float(len(keys) * 40)

        def repaint_arrival_keys(self, keys: tuple[object, ...]) -> None:
            self.repainted.append(keys)

    win = _ProbeWindow()
    live_tool = _Frag(key="live-1", source_identity="src-tool")
    saved_tool = _Frag(key="saved-1", source_identity="src-tool")
    saved_thought = _Frag(key="saved-2", source_identity="src-thought")

    # Live arrival fades in and starts a tail-follow glide.
    win.arrive_fragments((live_tool,), live=True)
    assert len(win.arrivals) == 1 and isinstance(win.arrivals[0], ArrivalFadeRun)
    assert isinstance(win.glide, ArrivalGlide)
    assert win.arrival_opacity("live-1") is not None

    # Saved commit of that same live source does not double-fade it, while a genuinely
    # new sibling fragment (e.g. thinking trace / bus message) in the same batch DOES fade.
    win.arrive_fragments((saved_tool, saved_thought), live=False)
    assert win.arrival_opacity("saved-1") is None
    assert win.arrival_opacity("saved-2") is not None

    # HeadReveal glides and shifts cleanly on layout changes.
    assert win.start_head_reveal(20.0) is True
    assert isinstance(win.head_reveal, HeadReveal)
    win.shift_arrival_motion(15.0)
    assert win.head_reveal.target == 35.0
    win.stop_arrival_motion()
    assert win.head_reveal is None and win.glide is None and not win.arrivals


def test_composer_pool_is_shared_by_both_frontends():
    """Both frontends inherit one semantic composer reuse pool (`WorkspaceComposerPool` on
    `WorkspaceViews`, `RebindableComposer` on `PromptComposer`, `ComposerPoolHost` on
    `DeliveryFailureView` and `QtConversation`)."""
    from toad.client.composer_pool import (
        ComposerDraft,
        ComposerPoolHost,
        RebindableComposer,
        WorkspaceComposerPool,
    )
    from toad.client.message_files import MessagePromptComposer
    from toad.client.prompt_composer import PromptComposer
    from toad.delivery_failure_view import DeliveryFailureView
    from toad.qt.composer import Composer
    from toad.qt.conversation import QtConversation
    from toad.qt.window import ConversationView, QtWorkspaceViews
    from toad.session_host import WorkspaceViews
    from toad.widgets.comms_chat import CommsChatView
    from toad.widgets.conversation import Conversation
    from toad.widgets.prompt import Prompt
    from toad.workspace_sessions import WorkspaceSessions

    _owned_by(WorkspaceViews, "composer_pool", WorkspaceSessions, QtWorkspaceViews)
    for member in ("on_composer", "flush_composer_applies", "clear_composer_applies", "workspace_composer_pool"):
        _owned_by(
            ComposerPoolHost,
            member,
            DeliveryFailureView,
            Conversation,
            CommsChatView,
            QtConversation,
            ConversationView,
        )
    assert issubclass(PromptComposer, RebindableComposer)
    assert issubclass(Prompt, RebindableComposer)
    assert issubclass(Composer, RebindableComposer)
    # A fresh tab checking out a pooled message composer keeps MessagePromptComposer's
    # open default (`takes_files=True`) until Core's ComposeAccess answers otherwise.
    assert ComposerDraft().takes_files is MessagePromptComposer.takes_files

    # Behavioural check: two tabs share one live composer instance, preserving per-tab
    # drafts, queuing background updates, and rescuing the composer on tab close.
    pool = WorkspaceComposerPool()

    class _FakeComposer(RebindableComposer):
        def __init__(self, host) -> None:
            self.host = host
            self.text = ""
            self.label = ""
            self.mentions: tuple[object, ...] = ()

        def capture_composer_draft(self) -> ComposerDraft:
            return ComposerDraft(text=self.text, label=self.label, mention_candidates=self.mentions)

        def rebind_conversation(self, host: ComposerPoolHost, draft: ComposerDraft) -> None:
            self.host = host
            self.text = draft.text
            self.label = draft.label
            self.mentions = draft.mention_candidates

    class _FakeHost(ComposerPoolHost):
        def __init__(self, name: str) -> None:
            self.name = name
            self.composer: _FakeComposer | None = None

        @property
        def active_composer(self):
            return self.composer

        def release_pooled_composer(self, composer: RebindableComposer) -> ComposerDraft:
            draft = composer.capture_composer_draft()
            self.composer = None
            return draft

    tab_a, tab_b, tab_c = _FakeHost("#comms"), _FakeHost("#model"), _FakeHost("#toad")
    built = 0

    def _build(host):
        nonlocal built
        built += 1
        return _FakeComposer(host)

    # First tab builds once (miss=1).
    comp_a, reused_a = pool.acquire(_FakeComposer, tab_a, lambda: _build(tab_a))
    tab_a.composer = comp_a
    assert not reused_a and built == 1 and pool.misses == 1 and pool.hits == 0
    comp_a.text = "draft for comms"
    comp_a.label = "#comms"

    # Second tab reuses the exact same instance (hit=1, built still 1!) with a clean draft.
    comp_b, reused_b = pool.acquire(_FakeComposer, tab_b, lambda: _build(tab_b))
    tab_b.composer = comp_b
    assert reused_b and comp_b is comp_a and built == 1 and pool.hits == 1
    assert tab_a.composer is None and comp_b.text == ""
    comp_b.text = "draft for model"

    # Background update queued on detached tab_a replays when tab_a reclaims the composer.
    tab_a.on_composer("mentions", lambda c: setattr(c, "mentions", ("@tristan",)))
    assert comp_b.mentions == ()

    # Returning to tab_a restores its draft and replays queued updates.
    comp_back, reused_back = pool.acquire(_FakeComposer, tab_a, lambda: _build(tab_a))
    tab_a.composer = comp_back
    tab_a.flush_composer_applies(comp_back)
    assert reused_back and comp_back is comp_a and built == 1
    assert comp_back.text == "draft for comms" and comp_back.mentions == ("@tristan",)

    # Closing tab_a rescues the live composer so tab_c still gets a pool hit (built still 1).
    pool.release(tab_a, keep_draft=False)
    assert tab_a.composer is None and pool.has(_FakeComposer)
    comp_c, reused_c = pool.acquire(_FakeComposer, tab_c, lambda: _build(tab_c))
    assert reused_c and comp_c is comp_a and built == 1 and comp_c.text == ""


def test_gui_and_tui_share_theme_tones_and_resolve_identical_colours() -> None:
    """Every surface tone, divider rule, sidebar row pair, tab chrome role, and editing
    badge colour must be owned once in `toad.client.theme_tones` / `toad.sidebar_rows` /
    `toad.client.prompt_stack` and resolve identically on Textual and Qt."""
    from pathlib import Path

    from agent_comms.messaging.display_references import ProjectReferences
    from ui_theme.catalog import SCHEMES
    from ui_theme.colour import Rgb, TerminalPalette
    from ui_theme.scheme import scheme_of_palette

    from toad.client.line_blocks import Divider, IncomingRole, OutgoingRole, Span
    from toad.client.prompt_stack import EditingModeBadge
    from toad.client.theme_tones import (
        ChannelAlternateRowToneColour,
        ChannelRowToneColour,
        FloatSurfaceTones,
        ScrollbarTones,
        SidebarToggleToneColour,
        TabHoverToneColour,
        WorkspaceTabTones,
    )
    from toad.markdown_links import LinkContext
    from toad.patch import DiffSettings
    from toad.qt.lines import QtLineRenderer
    from toad.qt.prompt_stack import QtEditingModeBadge
    from toad.qt.window import ChannelEntry, ThreadLine
    from toad.sidebar_rows import ChannelRowFace, ThreadRowFace
    from toad.widgets.comms_sidebar import ChannelHeaderRow, ThreadStatusRow
    from toad.widgets.prompt import EditingModeLabel
    from toad.workspace_chrome import WorkspaceHeader

    # 1. Shared row-tone ownership across Textual and Qt sidebar rows.
    _owned_by(ChannelRowFace, "row_tones", ChannelHeaderRow, ChannelEntry)
    _owned_by(ThreadRowFace, "row_tones", ThreadStatusRow, ThreadLine)
    assert ChannelEntry.row_tones == (ChannelRowToneColour, ChannelAlternateRowToneColour)
    assert ChannelHeaderRow.row_tones == ChannelEntry.row_tones
    assert ThreadLine.row_tones == ThreadStatusRow.row_tones

    # 2. Workspace tab chrome & editing badge ownership.
    assert WorkspaceHeader.tone is WorkspaceTabTones.bar_tone
    _owned_by(EditingModeBadge, "badge_foreground", EditingModeLabel, QtEditingModeBadge)
    _owned_by(EditingModeBadge, "badge_background", EditingModeLabel, QtEditingModeBadge)

    # 3. Every hoisted tone resolves identically on both catalog and pywal palettes.
    wal_palette = TerminalPalette(
        background=Rgb(0x0B, 0x0B, 0x1A),
        foreground=Rgb(0xC2, 0xC2, 0xC5),
        cursor=Rgb(0xC2, 0xC2, 0xC5),
        ansi=tuple(
            Rgb.parse(hex_str)
            for hex_str in (
                "#0b0b1a", "#857870", "#788d27", "#77866f",
                "#90a827", "#8f9466", "#797e87", "#c2c2c5",
                "#5a5a6f", "#857870", "#788d27", "#77866f",
                "#90a827", "#8f9466", "#797e87", "#c2c2c5",
            )
        ),
    )
    wal_scheme = scheme_of_palette("wal", wal_palette)
    links = LinkContext(Path("."), ProjectReferences())
    for scheme in (SCHEMES[0], wal_scheme):
        renderer = QtLineRenderer(scheme, links, DiffSettings())
        # Channel rows step toward PrimaryColour (not flat neutral sidebar).
        assert renderer.theme(ChannelRowToneColour) != renderer.theme(ThreadRowFace.row_tones[0])
        assert renderer.theme(ChannelAlternateRowToneColour) != renderer.theme(ChannelRowToneColour)
        # Tab strip / inactive tab / selected tab are three distinct stepped tiers so inter-tab gaps stay visible.
        assert renderer.theme(WorkspaceTabTones.bar_tone) != renderer.theme(WorkspaceTabTones.inactive_tab_tone)
        assert renderer.theme(WorkspaceTabTones.inactive_tab_tone) != renderer.theme(WorkspaceTabTones.selected_tab_tone)
        # Toggle bar, tab hover, scrollbar, and float tones resolve cleanly.
        for tone in (
            SidebarToggleToneColour,
            TabHoverToneColour,
            WorkspaceTabTones.bar_tone,
            WorkspaceTabTones.inactive_tab_tone,
            WorkspaceTabTones.selected_tab_tone,
            WorkspaceTabTones.underline_colour,
            WorkspaceTabTones.close_hover_colour,
            ScrollbarTones.track_colour,
            ScrollbarTones.thumb_colour,
            ScrollbarTones.active_colour,
            FloatSurfaceTones.background_tone,
            EditingModeBadge.badge_foreground,
            EditingModeBadge.badge_background,
        ):
            assert renderer.theme(tone).startswith("#")
        # Divider rule colour matches block.role (IncomingRole / OutgoingRole), matching Textual.
        for role in (IncomingRole, OutgoingRole):
            html = renderer.divider(Divider((Span("hdr", role),), role=role))
            assert f"background-color:{renderer.colour(role)}" in html


