"""Sequences both frontends took in their own overrides of one hook are the shared parent's:
a frontend answers only what is its own (NRA's sibling-override-step finding, 2026-11-22)."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from toad.client.history import WireView
from toad.client.keymap_browser import KeymapBrowsing
from toad.client.prompt_composer import PromptComposer
from toad.client.view_binding_protocols import BoundViewHost
from toad.flash_host import ErrorTone, FlashHost, SuccessTone
from toad.menus import MenuConversation


def test_a_flash_host_flashes_through_its_notice_in_the_tone_asked_for():
    flashed = []
    host = FlashHost()
    host.feedback = SimpleNamespace(flash=lambda content, **keywords: flashed.append((content, keywords)))

    host.flash("neutral")
    host.flash_success("done")
    host.flash_error("broke")

    assert flashed == [("neutral", {}), ("done", {"style": SuccessTone.declared_name}),
                       ("broke", {"style": ErrorTone.declared_name})]


def test_copying_a_block_is_one_sequence_and_an_empty_block_does_nothing():
    class Conversation(MenuConversation):
        def __init__(self, text: str) -> None:
            self.text, self.heard = text, []
            self.app = SimpleNamespace(copy_to_clipboard=lambda text: self.heard.append(("clipboard", text)))

        def flash(self, text: str) -> None:
            self.heard.append(("flash", text))

        def block_clipboard_text(self) -> str:
            return self.text

        def block_prompt_text(self) -> str:
            return self.text.upper()

        def append_to_prompt(self, text: str) -> None:
            self.heard.append(("prompt", text))

    held = Conversation("x = 1")
    held.copy_block_to_clipboard()
    held.copy_block_to_prompt()
    assert held.heard == [("clipboard", "x = 1"), ("flash", "Copied to clipboard"),
                          ("prompt", "X = 1"), ("flash", "Copied to prompt")]

    nothing = Conversation("")
    nothing.copy_block_to_clipboard()
    nothing.copy_block_to_prompt()
    assert nothing.heard == []


def test_a_painted_history_runs_the_views_own_part_then_the_application_then_submissions():
    heard = []
    view = SimpleNamespace(
        view_painted=lambda: heard.append("view"),
        app=SimpleNamespace(history_displayed=lambda: heard.append("application")),
        submissions=SimpleNamespace(settle=lambda: heard.append("submissions")),
    )
    BoundViewHost.history_painted(view)
    assert heard == ["view", "application", "submissions"]


def test_a_sent_message_follows_the_end_and_reads_it():
    heard = []

    async def refresh():
        heard.append("refresh")

    view = SimpleNamespace(window=SimpleNamespace(jump_to_latest=lambda: heard.append("latest")), _refresh=refresh)
    asyncio.run(WireView.show_sent(view, object()))
    assert heard == ["latest", "refresh"]


def test_a_returned_draft_is_appended_only_when_the_draft_does_not_hold_it():
    appended = []
    composer = SimpleNamespace(text="typed", restored_suffix=PromptComposer.restored_suffix, append_to_draft=appended.append)
    PromptComposer.restore_draft(composer, "returned")
    PromptComposer.restore_draft(composer, "typed")
    assert appended == ["\n\nreturned"]


def test_the_keymap_selection_is_the_state_reading_the_native_cursor():
    browser = SimpleNamespace(selected_cell=lambda: (3, 1), state=SimpleNamespace(select=lambda row, column: (row, column)))
    assert KeymapBrowsing.selected(browser) == (3, 1)


def test_neither_frontend_writes_these_sequences_itself():
    from toad.client.conversation_capabilities import ConversationActivity
    from toad.qt.composer import Composer as QtComposer
    from toad.qt.keymap_screen import QtKeymapScreen
    from toad.qt.thread_view import QtThreadView
    from toad.qt.window import ConversationView
    from toad.screens.keymap import KeymapScreen
    from toad.widgets.comms_chat import CommsChatView
    from toad.widgets.conversation import Conversation
    from toad.widgets.prompt import Prompt

    for owner, name, classes in (
        (FlashHost, "flash", (Conversation, ConversationView)),
        (FlashHost, "flash_success", (Conversation, ConversationView)),
        (FlashHost, "flash_error", (Conversation, ConversationView)),
        (MenuConversation, "copy_block_to_clipboard", (Conversation, ConversationView)),
        (MenuConversation, "copy_block_to_prompt", (Conversation, ConversationView)),
        (BoundViewHost, "history_painted", (Conversation, QtThreadView)),
        (WireView, "show_sent", (CommsChatView, ConversationView)),
        (ConversationActivity, "update_channel_mentions", (CommsChatView, ConversationView)),
        (PromptComposer, "restore_draft", (Prompt, QtComposer)),
        (KeymapBrowsing, "selected", (KeymapScreen, QtKeymapScreen)),
    ):
        for view in classes:
            assert getattr(view, name) is getattr(owner, name), (view.__name__, name)


def test_a_command_catalog_is_the_views_only_if_the_view_did_not_change_while_it_was_read(monkeypatch):
    import pytest

    from toad import command_catalog
    from toad.client.commands import CommandContextChanged
    from toad.command_catalog import ReadsCommandCatalog
    from toad.qt.conversation import QtConversation
    from toad.widgets.conversation import Conversation

    for view in (Conversation, QtConversation):
        assert view.read_command_catalog is ReadsCommandCatalog.read_command_catalog, view

    async def target_context():
        return None

    def reading(change):
        binding = SimpleNamespace(presentation=SimpleNamespace(commands=()))
        view = SimpleNamespace(app=object(), agent_binding=binding, local_commands=object(), is_attached=True,
                               navigation="channel", command_target_context=target_context)
        view.command_navigation = lambda: view.navigation

        async def read(app, advertised, context, local):
            await context
            change(view)
            return "catalog"

        monkeypatch.setattr(command_catalog.CommandCatalog, "read", read)
        return ReadsCommandCatalog.read_command_catalog(view)

    assert asyncio.run(reading(lambda view: None)) == "catalog"
    for change in (
        lambda view: setattr(view, "is_attached", False),
        lambda view: setattr(view, "navigation", "another channel"),
        lambda view: setattr(view, "agent_binding", SimpleNamespace(presentation=SimpleNamespace(commands=()))),
    ):
        with pytest.raises(CommandContextChanged):
            asyncio.run(reading(change))


def test_a_wire_views_refresh_is_deferred_once_the_view_is_detached():
    from toad.client.history_state import DEFERRED_WORK
    from toad.qt.window import ConversationView
    from toad.widgets.comms_chat import CommsChatView

    for view in (CommsChatView, ConversationView):
        assert view._refresh is WireView._refresh, view
    scheduled = []
    history = SimpleNamespace(page_source=SimpleNamespace(schedule_refresh=lambda view: scheduled.append(view) or "work"))
    attached = SimpleNamespace(is_attached=True, message_history=history)
    detached = SimpleNamespace(is_attached=False, message_history=history)
    assert asyncio.run(WireView._refresh(attached)) == "work"
    assert asyncio.run(WireView._refresh(detached)) is DEFERRED_WORK
    assert scheduled == [attached]


def test_closing_rendering_closes_the_renderer_every_frontend_submits_to():
    from toad.app import ToadApp
    from toad.client.application import ClientApplication
    from toad.qt.window import QtToadApp

    for application in (ToadApp, QtToadApp):
        assert application.close_rendering is ClientApplication.close_rendering, application
    closed = []

    async def aclose():
        closed.append("renderer")

    asyncio.run(ClientApplication.close_rendering(SimpleNamespace(render_processes=SimpleNamespace(aclose=aclose))))
    assert closed == ["renderer"]


def test_a_command_target_is_built_from_where_the_view_says_its_thread_and_navigation_are():
    import pytest

    from toad.client.commands import CommandContextChanged
    from toad.client.history import WireView
    from toad.command_catalog import AddressesItsThread
    from toad.qt.thread_view import QtThreadView
    from toad.qt.window import ConversationView
    from toad.widgets.comms_chat import CommsChatView
    from toad.widgets.conversation import Conversation

    for view in (Conversation, QtThreadView):
        assert view.command_target_context is AddressesItsThread.command_target_context, view
    # A wire view's commands address what its page source reads, in both frontends.
    for view in (CommsChatView, ConversationView):
        assert view.command_target_context is WireView.command_target_context, view
    asked = []
    scope = SimpleNamespace(
        navigation_context=SimpleNamespace(project_path="/project", owner_mode="mode"),
        thread_identity=SimpleNamespace(command_target=lambda build: asked.append(build) or "context"),
    )
    view = SimpleNamespace(
        app=SimpleNamespace(coordination_access=SimpleNamespace(observation=SimpleNamespace(observed=lambda: "observed"))),
        is_attached=True, command_target_scope=lambda: scope)
    assert asyncio.run(AddressesItsThread.command_target_context(view)) == "context"
    assert len(asked) == 1
    view.is_attached = False
    with pytest.raises(CommandContextChanged):
        asyncio.run(AddressesItsThread.command_target_context(view))


def test_no_view_or_application_a_frontend_makes_leaves_a_hook_abstract():
    """A hoist adds an abstract hook, and a class that leaves one abstract cannot be made.
    Qt's wire view was left without `command_target_scope` (2026-11-22): the shipped-app run
    refused it and no unit test did, because none makes a view."""
    import inspect

    from toad.app import ToadApp
    from toad.qt.acp_tab import QtAcpSessionView
    from toad.qt.window import ConversationView, QtToadApp
    from toad.widgets.comms_chat import CommsChatView
    from toad.widgets.conversation import Conversation

    for made in (Conversation, CommsChatView, ToadApp, ConversationView, QtAcpSessionView, QtToadApp):
        left = [name for name in dir(made)
                if getattr(inspect.getattr_static(made, name, None), "__isabstractmethod__", False)]
        assert not left, (made.__name__, left)


def test_a_channel_header_is_presented_in_one_sequence_from_an_unpainted_channel():
    from toad.client.sidebar_models import UnpaintedChannel
    from toad.qt.window import QtChannelGroup
    from toad.sidebar_contracts import ChannelGroupRows
    from toad.widgets.comms_sidebar import ChannelGroup

    for group in (ChannelGroup, QtChannelGroup):
        assert group.present is ChannelGroupRows.present, group
    heard = []
    group = SimpleNamespace(
        channel=UnpaintedChannel("#comms"), unread_counts="counts",
        row=SimpleNamespace(present_channel=lambda channel, counts: heard.append(("row", channel.name, counts))),
        sort_choice=SimpleNamespace(update_order=lambda order: heard.append(("order", order))),
        header_presented=lambda previous, channel: heard.append(("frontend", type(previous).__name__, channel.name)),
    )
    shown = SimpleNamespace(name="#comms", order="by activity", pinned_members=frozenset({"claude-a"}))
    assert ChannelGroupRows.present(group, shown) == frozenset({"claude-a"})
    assert group.channel is shown
    assert heard == [("row", "#comms", "counts"), ("order", "by activity"), ("frontend", "UnpaintedChannel", "#comms")]


def test_changed_threads_repaint_only_the_rows_a_group_shows_and_the_model_has():
    from toad.qt.window import QtChannelGroup
    from toad.sidebar_contracts import ChannelGroupRows
    from toad.widgets.comms_sidebar import ChannelGroup

    for group in (ChannelGroup, QtChannelGroup):
        assert group.repaint_members is ChannelGroupRows.repaint_members, group
    painted = []
    group = SimpleNamespace(
        rows={"shown": "row of shown", "gone from the model": "row"},
        sidebar=SimpleNamespace(model_state=SimpleNamespace(shown=SimpleNamespace(threads=SimpleNamespace(rows={"shown": 1, "not listed here": 2})))),
        update_row=lambda name, row: painted.append((name, row)),
        accepts_members=lambda: True,
    )
    ChannelGroupRows.repaint_members(group, frozenset({"shown", "gone from the model", "not listed here"}))
    assert painted == [("shown", "row of shown")]
    group.accepts_members = lambda: False
    ChannelGroupRows.repaint_members(group, frozenset({"shown"}))
    assert painted == [("shown", "row of shown")]


def test_the_shared_group_contract_does_not_stand_between_a_group_and_its_own_answer():
    """Textual's channel group narrows `SidebarGroup.accepts_members` with `super()`; a
    declaration of it on the contract, which comes first in the group's order, is what that
    `super()` would reach."""
    from toad.sidebar_contracts import ChannelGroupRows
    from toad.widgets.comms_sidebar import ChannelGroup
    from toad.widgets.sidebar_tree import SidebarGroup

    assert "accepts_members" not in vars(ChannelGroupRows)
    after = ChannelGroup.__mro__[ChannelGroup.__mro__.index(ChannelGroup) + 1:]
    assert next(owner for owner in after if "accepts_members" in vars(owner)).__name__ == SidebarGroup.__name__


def test_every_view_a_frontend_makes_hears_its_historys_finished_source_work():
    """The shared pager publishes that its source work finished. A thread view retries the
    publication that waited for it and a channel view reconciles an observation that arrived
    during it, in both frontends: Qt's history published the event to nobody."""
    from toad.core.source_events import TranscriptSourceWorkFinished
    from toad.qt.acp_tab import QtAcpSessionView
    from toad.qt.mailbox_view import QtMailboxView
    from toad.qt.window import ConversationView
    from toad.widgets.comms_chat import CommsChatView
    from toad.widgets.conversation import Conversation

    def owners(view: type) -> dict[str, str]:
        return {name: next(owner.__name__ for owner in view.__mro__ if name in vars(owner))
                for name in view.handler_names_for(TranscriptSourceWorkFinished)}

    retries = {"on_transcript_source_work_finished": "BoundViewHost"}
    reconciles = {"reconcile_finished_source_work": "WireView"}
    assert owners(Conversation) == owners(QtAcpSessionView) == owners(QtMailboxView) == retries
    assert owners(ConversationView) == reconciles
    assert owners(CommsChatView) == reconciles | retries


def test_qts_history_publishes_to_its_view_which_hears_it_on_its_loop_with_the_history_as_publisher():
    from toad.client.subscribers import CoreObserver
    from toad.core.source_events import TranscriptSourceWorkFinished
    from toad.core_event_carrier import CoreEventReceiver
    from toad.qt.core_events import QtCoreObserver, QtPublication
    from toad.qt.history import QtConversationHistory

    # One way to hear a stream whole, for both frontends' views.
    assert CoreEventReceiver.subscribe_core is CoreObserver.subscribe_core is QtCoreObserver.subscribe_core

    heard, queued = [], []

    class View(CoreObserver):
        deliver = queued.append
        post_core_event = QtCoreObserver.post_core_event

        async def dispatch(self, event, message):
            heard.append((event, message.publisher, type(message)))

    class History:
        publish_core = QtConversationHistory.publish_core
        core_publications = QtConversationHistory.core_publications

        def __init__(self, view) -> None:
            self.view = view

    QtConversationHistory.core_publications.__set_name__(History, "core_publications")
    history = History(View())
    event = TranscriptSourceWorkFinished()
    history.publish_core(event)

    assert heard == [] and len(queued) == 1  # on the view's loop, after the deliveries before it
    asyncio.run(queued[0]())
    assert heard == [(event, history, QtPublication)]


def test_a_thread_views_transcript_retries_when_a_history_releases_its_source():
    retried = []
    view = BoundViewHost.__new__(type("View", (BoundViewHost,), {}))
    view.transcript = SimpleNamespace(source_work_finished=retried.append)
    view.on_transcript_source_work_finished(object(), object())
    assert retried == [view]


class _Revision:
    def __init__(self, roster_moved: bool = False) -> None:
        self.roster_moved = roster_moved

    def changed_since(self, view, held) -> bool:
        return self.roster_moved


def _wire_view(heard: list, revision, **history):
    class View(WireView):
        mode = "comms"
        is_attached = True

        def shows(self, root, conversation) -> bool:
            return True

        def read_thread_config(self) -> None:
            heard.append("config")

        def source_read(self) -> None:
            heard.append("read ended")

        def source_drawn(self) -> None:
            heard.append("drawn")

        async def _refresh(self):
            heard.append("refresh")

    view = View.__new__(View)
    view.app = SimpleNamespace(coordination_access=SimpleNamespace(revision=revision, **history.pop("access", {})))
    view.submissions = SimpleNamespace(settle=lambda: heard.append("settled"))
    view.message_history = SimpleNamespace(**history)
    return view


def test_a_wire_views_refresh_reads_then_settles_then_draws_then_reads_config_when_the_roster_moved():
    heard: list = []

    async def read_changes() -> None:
        heard.append("read")

    announced = _Revision(roster_moved=True)
    view = _wire_view(heard, announced, read_changes=read_changes)
    asyncio.run(view._refresh_source())
    assert heard == ["read", "read ended", "settled", "drawn", "config"]
    assert view._refreshed_from is announced and view._config_revision is announced

    heard.clear()
    still = _Revision()
    view.app.coordination_access.revision = still
    asyncio.run(view._refresh_source())
    assert heard == ["read", "read ended", "settled", "drawn"] and view._config_revision is announced


def test_a_wire_views_failed_read_still_ends_the_read_and_draws_nothing():
    heard: list = []

    async def read_changes() -> None:
        raise OSError("bus gone")

    view = _wire_view(heard, _Revision(roster_moved=True), read_changes=read_changes)
    try:
        asyncio.run(view._refresh_source())
    except OSError:
        pass
    assert heard == ["read ended"] and view._refreshed_from is None


def test_a_wire_view_reads_again_when_the_observer_announced_during_its_historys_work():
    heard: list = []
    began_from, now = _Revision(), _Revision()
    source = SimpleNamespace(uses_observation=lambda observed: True)
    history = dict(page_source=source, state=SimpleNamespace(accepts_source_work=True),
                   access=dict(observation=SimpleNamespace(observed=lambda: "observed")))
    view = _wire_view(heard, now, **history)
    view._refreshed_from = began_from

    # Another history's work is not this view's to reconcile.
    asyncio.run(view.reconcile_finished_source_work(object(), SimpleNamespace(publisher=object())))
    assert heard == []

    asyncio.run(view.reconcile_finished_source_work(object(), SimpleNamespace(publisher=view.message_history)))
    assert heard == ["settled", "refresh"]

    # Nothing was announced since the refresh began, and the stores are what was read: no read.
    heard.clear()
    view._refreshed_from = now
    source.revision = SimpleNamespace(matches_stores=lambda revision: True)
    asyncio.run(view.reconcile_finished_source_work(object(), SimpleNamespace(publisher=view.message_history)))
    assert heard == ["settled"]


def test_a_name_wave_answers_its_cells_only_while_it_runs():
    from toad.client.name_wave import NameWave
    from toad.qt.name_wave import QtTabWave
    from toad.qt.window import ConversationRow
    from toad.widgets.selection import ViewLabel

    for line in (ViewLabel, QtTabWave, ConversationRow):
        assert line.wave_span is NameWave.wave_span, line

    class Line(NameWave):
        running = False

        def wave_running(self) -> bool:
            return self.running

        def wave_cells(self):
            return (2, 5)

    line = Line()
    assert line.wave_span() is None
    line.running = True
    assert line.wave_span() == (2, 5)


def test_a_view_returns_to_the_direct_conversation_it_last_opened_in_both_frontends():
    from toad.navigation_context import NavigationDestination, NavigationOwner
    from toad.qt.mailbox_view import QtMailboxView
    from toad.screens.main import MainScreen

    notices, opened = [], []

    class Destination(NavigationDestination):
        def selected(self, owner) -> None:
            owner.remember_direct_target(self)

        async def open(self, context) -> str:
            opened.append(context)
            return "mode"

    class Owner(NavigationOwner):
        navigation_context = SimpleNamespace(app=SimpleNamespace(show_info=lambda text, title: notices.append((text, title))))

    owner = Owner()
    asyncio.run(owner.open_direct_messages())
    assert notices == [("Choose Direct messages from an agent's context menu", "Direct messages")] and opened == []

    asyncio.run(owner.open_sidebar_target(Destination()))
    asyncio.run(owner.open_direct_messages())
    assert len(opened) == 2  # the one chosen, then "open my last DM"

    # The same answer in every view that navigates: neither frontend writes it again.
    for view in (QtMailboxView, MainScreen):
        assert view.open_direct_messages is NavigationOwner.open_direct_messages, view
        assert view.remember_direct_target is NavigationOwner.remember_direct_target, view


def test_closing_the_window_retires_every_sidebar_line_before_the_tree_is_destroyed():
    from toad.qt.window import Sidebar

    retired = []

    class Line:
        def __init__(self, name: str, *children: "Line") -> None:
            self.name, self.children = name, children

        def subtree(self):
            yield self
            for child in self.children:
                yield from child.subtree()

        def retired(self) -> None:
            retired.append(self.name)

    tree = SimpleNamespace(items=lambda: iter((Line("group", Line("a"), Line("b")), Line("status"))))
    Sidebar.retire_all(tree)
    assert retired == ["group", "a", "b", "status"]


def test_home_reads_who_the_reader_is_off_the_loop_once_before_it_opens_a_target():
    from toad.client.session_scope import HomeSessionOrigin
    from toad.navigation_context import HomeNavigation, NavigationDestination
    from toad.qt.window import QtWelcomeOrigin
    from toad.screens.welcome import WelcomeScreen
    from toad.thread_identity import NoThreadIdentity

    for home in (QtWelcomeOrigin, WelcomeScreen):
        for name in ("prepare_history_origin", "read_history_identity", "thread_identity"):
            owner = next(base for base in home.__mro__ if name in vars(base))
            assert owner is HomeSessionOrigin, (home, name, owner)
        assert next(base for base in home.__mro__ if "open_sidebar_target" in vars(base)) is HomeNavigation, home
    # The one thing each frontend says: how it announces that home's identity was read.
    assert "home_identity_read" in vars(WelcomeScreen) and "home_identity_read" not in vars(QtWelcomeOrigin)

    steps, opened = [], []
    async def run_thread(function, *arguments):
        steps.append(("worker", function.__name__))
        return function(*arguments)

    observed = SimpleNamespace(root="root", user_identity=lambda project: SimpleNamespace(incarnation=SimpleNamespace(name="reader")))
    app = SimpleNamespace(preparation=SimpleNamespace(run_thread=run_thread),
                          coordination_access=SimpleNamespace(observation=SimpleNamespace(observed=lambda: observed)))

    class Destination(NavigationDestination):
        async def open(self, context) -> str:
            steps.append(("open", context.identity if hasattr(context, "identity") else None))
            opened.append(context)
            return "mode"

    class Home(HomeSessionOrigin, HomeNavigation):
        project_path = "project"

        def __init__(self) -> None:
            self.app = app

        @property
        def navigation_context(self):
            return SimpleNamespace(identity=self.thread_identity)

    home = Home()
    assert isinstance(home.thread_identity, NoThreadIdentity)  # nothing is read until a target opens
    asyncio.run(home.open_sidebar_target(Destination()))
    assert steps[0] == ("worker", "read_history_identity") and steps[1][0] == "open"
    assert home.thread_identity.thread_name() == "reader"


def test_a_view_that_navigates_nowhere_still_says_direct_messages_are_unavailable():
    from toad.navigation_context import NoNavigationOwner

    notices = []
    owner = NoNavigationOwner(SimpleNamespace(show_info=lambda text, title: notices.append((text, title))))
    asyncio.run(owner.open_direct_messages())
    assert notices == [("Direct messages are unavailable from this view", "Direct messages")]


def test_a_host_that_composes_no_loading_splash_has_nothing_to_retire():
    from toad.client.history_state import UnboundTranscript
    from toad.qt.acp_tab import QtAcpSessionView
    from toad.widgets.conversation import Conversation

    # The transcript states ask every host to retire its splash when a local tab mounts:
    # Qt's agent tab inherits the contract's "none composed" answer, Textual's removes its widget.
    assert QtAcpSessionView.retire_loading_splash is BoundViewHost.retire_loading_splash
    assert Conversation.retire_loading_splash is not BoundViewHost.retire_loading_splash

    asked = []
    host = SimpleNamespace(retire_loading_splash=lambda: asked.append("retired"))
    owner = SimpleNamespace(view=host, call_after_refresh=lambda callback: callback())
    UnboundTranscript().mounted(owner)
    assert asked == ["retired"]


def test_closing_a_qt_history_stops_the_rows_its_delegate_is_still_rendering():
    from toad.qt.history import QtConversationHistory

    stopped = []
    # A concrete stand-in for the abstract history: close touches only its source and window.
    window = SimpleNamespace(rows=SimpleNamespace(cleanup=lambda: stopped.append("cleanup")))
    history_type = type("History", (QtConversationHistory,), {"__abstractmethods__": frozenset(), "window": window})
    history = object.__new__(history_type)
    history.page_source = SimpleNamespace(close=lambda: stopped.append("source"), through="through", runtime="runtime")
    history.close()

    # The workers' rows must not land in a delegate Qt is about to delete: a render that
    # finished after its tab closed raised "QTimer already deleted" into the event loop.
    assert stopped == ["source", "cleanup"] and history.attached is False


def refreshing_view(*, current: list[bool], status=None):
    """A WireView with a recording page source; `current` answers each source_is_current in turn."""
    import asyncio

    from toad.client.history import WireView

    seen: list[str] = []
    answers = iter(current)

    async def source_is_current(snapshot):
        return next(answers, True)

    async def compose_access():
        seen.append("compose")
        return SimpleNamespace(read_only=False)

    async def update_mentions(view):
        seen.append("mentions")

    async def status_text(*, read_only):
        if isinstance(status, Exception):
            raise status
        seen.append("status")
        return "status line"

    history = SimpleNamespace(
        page_source=SimpleNamespace(compose_access=compose_access, update_mentions=update_mentions,
                                    status_text=status_text),
        source_snapshot=lambda: "snapshot", source_is_current=source_is_current)

    async def refresh_composer(self, compose):
        seen.append("composer")

    async def thread_label_read(self):
        seen.append("label")

    members = {"__abstractmethods__": frozenset(), "message_history": history,
               "refresh_composer": refresh_composer, "thread_label_read": thread_label_read,
               "mentions_read": lambda self: seen.append("mentions-read"),
               "thread_status_shown": lambda self: seen.append("status-shown"), "thread_status": ""}
    view = object.__new__(type("View", (WireView,), members))
    asyncio.run(view._refresh_thread_config())
    return view, seen


def test_the_thread_config_refresh_draws_each_answer_in_order_and_shows_the_status():
    view, seen = refreshing_view(current=[])

    assert seen == ["label", "compose", "composer", "mentions", "mentions-read", "status", "status-shown"]
    assert view.thread_status == "status line"


def test_a_source_replaced_during_the_thread_config_refresh_shows_nothing_more():
    # Fenced after the label read's snapshot check, then after compose access: the third check fails.
    view, seen = refreshing_view(current=[True, True, False])

    assert seen == ["label", "compose", "composer", "mentions"]
    assert view.thread_status == ""


def test_a_read_core_asks_to_repeat_shows_no_status():
    from agent_comms.coordination.errors import ReadAgain

    view, seen = refreshing_view(current=[], status=ReadAgain("again"))

    assert "status-shown" not in seen and view.thread_status == ""
