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


def test_a_following_window_stays_on_the_tail_when_its_height_changes():
    from toad.qt.history import QtHistoryWindow

    placed = []
    window = SimpleNamespace(follows_tail=True, widget_gone=False, follow_latest=lambda: placed.append("tail"))

    QtHistoryWindow.keep_tail_after_resize(window, 800, 694)  # the composer replaced its placeholder
    QtHistoryWindow.keep_tail_after_resize(window, 694, 694)  # a width change moved nothing vertically
    window.follows_tail = False
    QtHistoryWindow.keep_tail_after_resize(window, 694, 500)  # a reader reading older history stays put
    window.follows_tail, window.widget_gone = True, True
    QtHistoryWindow.keep_tail_after_resize(window, 500, 400)  # a destroyed window has no reader

    assert placed == ["tail"]


def test_surface_settings_goal_workspace_and_history_sequences_live_on_their_shared_parents():
    from toad.agent_surface import AttachedSurfaceBinding
    from toad.client.history import ReadMarkedHistory, WireView
    from toad.client.history_pager import HistoryPager
    from toad.client.view_settings import ViewSettingsOwner
    from toad.configured_view import ConfiguredView
    from toad.goal_controls import GoalControlsSession
    from toad.goal_interaction import GoalSession
    from toad.qt.agent_surface import QtSurfaceBinding
    from toad.qt.conversation import QtConversation
    from toad.qt.goal import QtGoalSession
    from toad.qt.history import QtConversationHistory
    from toad.qt.window import ConversationView, QtWorkspaceViews
    from toad.session_host import WorkspaceViews
    from toad.surface_binding import ViewSurfaceBinding
    from toad.transcript_source_preparation import TranscriptSourcePreparation
    from toad.widgets.transcript_history import LineHistory
    from toad.widgets.wire_history import WireHistory
    from toad.wire_conversation_view import WireConversationView
    from toad.workspace_sessions import WorkspaceSessions

    for owner, name, leaves in (
        (ViewSurfaceBinding, "owns_publication", (AttachedSurfaceBinding, QtSurfaceBinding)),
        (ViewSurfaceBinding, "present_tool", (AttachedSurfaceBinding, QtSurfaceBinding)),
        (ViewSurfaceBinding, "present_permission", (AttachedSurfaceBinding, QtSurfaceBinding)),
        (ViewSettingsOwner, "configuration_identity", (ConfiguredView, QtConversation)),
        (GoalControlsSession, "unavailable", (GoalSession, QtGoalSession)),
        (GoalControlsSession, "show_history", (GoalSession, QtGoalSession)),
        (GoalControlsSession, "open_edit", (GoalSession, QtGoalSession)),
        (WorkspaceViews, "require", (WorkspaceSessions, QtWorkspaceViews)),
        (WorkspaceViews, "origin", (WorkspaceSessions, QtWorkspaceViews)),
        (WorkspaceViews, "detach", (WorkspaceSessions, QtWorkspaceViews)),
        (HistoryPager, "followed_here", (TranscriptSourcePreparation, QtConversationHistory)),
        (HistoryPager, "read_ahead", (LineHistory, QtConversationHistory)),
        (ReadMarkedHistory, "mark_visible_after_paint", (WireHistory, QtConversationHistory)),
        (WireView, "shows", (WireConversationView, ConversationView)),
    ):
        for leaf in leaves:
            assert getattr(leaf, name) is getattr(owner, name), (leaf.__name__, name)


def test_goal_controls_edit_checks_ownership_before_presenting_and_saving():
    import pytest
    from agent_comms.errors import GoalRefused
    from toad.goal_controls import GoalControlsSession

    presented, saved = [], []
    goal = SimpleNamespace(id="g1", text="old")
    binding = SimpleNamespace(edit_goal=lambda g, text: saved.append((g, text)) or "edited")

    class Session(GoalControlsSession):
        owned = True

        @property
        def display(self):
            return SimpleNamespace(snapshot=SimpleNamespace(require=lambda: goal), heading=lambda ex: "Paused")

        @property
        def execution(self):
            return "exec"

        @property
        def host(self):
            return SimpleNamespace()

        @property
        def binding(self):
            return binding

        def owns(self, source) -> bool:
            return self.owned and source is binding

        async def refresh(self, source) -> None:
            pass

        def report_unavailable(self, heading: str) -> None:
            presented.append(("unavailable", heading))

        def present(self, view) -> None:
            presented.append(("present", view))

        def history_view(self, page):
            return ("history", page)

        async def edit_view(self, target_goal, on_save):
            return (target_goal, on_save)

        def toggle_collapsed(self) -> None:
            pass

    session = Session()
    session.unavailable()
    session.show_history(binding, "page")
    asyncio.run(session.open_edit())
    assert presented[0] == ("unavailable", "Paused")
    assert presented[1] == ("present", ("history", "page"))
    target_goal, on_save = presented[2][1]
    assert target_goal is goal

    # Saving while still owning the binding writes through the shared envelope.
    async def run_save():
        async def fake_write(src, op):
            return op
        session.write = fake_write
        await on_save("new")
        session.owned = False
        with pytest.raises(GoalRefused):
            await on_save("stale")

    asyncio.run(run_save())
    assert saved == [(goal, "new")]


def test_workspace_views_origin_respects_navigation_membership_and_resident_fallback():
    from toad.client.session_scope import NoSessionOrigin
    from toad.session_host import WorkspaceViews

    class Views(WorkspaceViews):
        def __init__(self, registered: set[str]) -> None:
            self.app = SimpleNamespace(session_navigation=SimpleNamespace(get=lambda key: object() if key in registered else None))
            self.views = {}
            self.detached = []

        def navigation_owner(self):
            return None

        def view_detached(self, view) -> None:
            self.detached.append(view)

        async def finish(self, view) -> None:
            pass

    views = Views({"tab-1"})
    live = SimpleNamespace(origin="live-origin")
    dying = SimpleNamespace(origin="dying-origin")
    views.views["tab-1"] = live
    views.views["tab-2"] = dying
    assert views.require("tab-1") is live
    assert views.origin("tab-1") == "live-origin"
    assert isinstance(views.origin("tab-2"), NoSessionOrigin)
    assert views.detach("tab-1") is live and views.detached == [live] and "tab-1" not in views.views


def test_committed_history_page_added_and_transcript_coverage_are_shared_across_frontends():
    from textual.message import Message

    from toad.client.committed_history import CommittedHistoryBase
    from toad.client.history_coverage import ReportsCoveredPages
    from toad.client.source_resumption import ResumesSource
    from toad.core_event_carrier import CoreEventMessage
    from toad.qt.core_events import QtPublication
    from toad.qt.history import QtConversationHistory
    from toad.qt.thread_view import QtThreadView
    from toad.qt.transcript_history import QtTranscriptHistory
    from toad.widgets.conversation import Conversation
    from toad.widgets.transcript_history import ProjectedTranscriptHistory, TranscriptHistory

    assert TranscriptHistory._page_added is CommittedHistoryBase._page_added
    assert QtTranscriptHistory._page_added is CommittedHistoryBase._page_added
    assert QtConversationHistory._page_added is ResumesSource._page_added
    assert ProjectedTranscriptHistory._page_added is not CommittedHistoryBase._page_added

    assert Conversation.on_transcript_coverage is BoundViewHost.on_transcript_coverage
    assert QtThreadView.on_transcript_coverage is BoundViewHost.on_transcript_coverage
    assert CoreEventMessage.stop is Message.stop
    QtPublication(event=object(), subscription=object()).stop()

    joined = []
    history = SimpleNamespace(
        view=SimpleNamespace(
            transcript=SimpleNamespace(
                binding=SimpleNamespace(covered=lambda *args: ("completion", args)),
            ),
            join_completion=joined.append,
        )
    )
    ReportsCoveredPages.page_covered(history, SimpleNamespace(events=()))
    assert len(joined) == 1 and joined[0][0] == "completion"


def test_qt_live_blocks_survive_page_range_changes_and_retire_only_by_commit_coverage():
    from acp import schema
    from agent_comms.acp_extension import InputStartedUpdate, NoQueueScope
    from agent_comms.transcript.transcript_events import ReportedInputId, UserTranscript

    from toad.commit_claims import RetainedBlockClaim, StartedInputClaim
    from toad.core.source_events import TranscriptCoverage
    from toad.qt.agent_surface import QtTerminalBlock, QtToolBlock
    from toad.qt.history import QtHistoryWindow
    from toad.qt.live_turn import QtLiveBlock, QtResponseBlock, QtThoughtBlock, QtUserInputBlock
    from toad.qt.thread_view import QtThreadView
    from toad.transcript_publication import BoundView
    from toad.widgets.committed_presentation import CommitTranscript, block_claim

    redrawn = []
    window = SimpleNamespace(
        live_blocks=[],
        history=SimpleNamespace(pages=()),
        show_pages=lambda: redrawn.append("show"),
    )
    window.retire_live = QtHistoryWindow.retire_live.__get__(window, SimpleNamespace)

    started = InputStartedUpdate("hello", NoQueueScope(), None, "in-1")
    covered_input = QtUserInputBlock(window, "hello", claim=StartedInputClaim(started))
    uncovered_response = QtResponseBlock(window, "still streaming or uncommitted")
    uncovered_response.finished = True
    thought = QtThoughtBlock(window, "thinking")
    tool = QtToolBlock(window, schema.ToolCall(tool_call_id="tc-1", title="read", status="completed"))
    note = QtLiveBlock(window, "local help note")
    note.finished = True
    terminal = QtTerminalBlock(window, "term-1", SimpleNamespace(command="ls"))
    window.live_blocks = [covered_input, uncovered_response, thought, tool, note, terminal]

    # Claims match Textual: transcript-backed live rows retire; local notes and terminals stay retained.
    assert block_claim(covered_input).retires
    assert block_claim(uncovered_response).retires
    assert block_claim(thought).retires
    assert block_claim(tool).retires
    assert isinstance(block_claim(note), RetainedBlockClaim)
    assert isinstance(block_claim(terminal), RetainedBlockClaim)

    # Scrolling / filtering / range changes must NEVER drop finished live blocks.
    QtHistoryWindow.committed_pages_changed(window)
    assert window.live_blocks == [covered_input, uncovered_response, thought, tool, note, terminal]
    assert redrawn == ["show"]

    # Coverage retires ONLY the covered input; uncovered response, thought, tool, note and terminal stay.
    retired_from_output = []
    summaries = []
    published_events = []
    class History:
        outgoing_coverage = frozenset()

        def covered_sequences(self, _seqs):
            return frozenset()

    history = History()

    class Output:
        async def retire_presentations(self, blocks):
            retired_from_output.extend(blocks)

    view = SimpleNamespace(
        transcript_history=history,
        messages=window,
        output=Output(),
        window=window,
        refresh_session_summary=lambda: summaries.append("summary"),
    )
    view.contents = view
    view.live_blocks = QtThreadView.live_blocks.fget(view)
    view.retire_blocks = QtThreadView.retire_blocks.__get__(view, SimpleNamespace)
    view.protected_blocks = QtThreadView.protected_blocks.__get__(view, SimpleNamespace)

    binding = BoundView(view)
    owner = SimpleNamespace(events=SimpleNamespace(publish=published_events.append))
    coverage = TranscriptCoverage((UserTranscript("hello", position=1, timestamp=0.0, native_id=ReportedInputId("in-1")),))

    async def apply_coverage():
        await binding.covered(owner, coverage, history)

    asyncio.run(apply_coverage())

    assert retired_from_output == [covered_input]
    assert window.live_blocks == [uncovered_response, thought, tool, note, terminal]
    assert summaries == ["summary"]
    assert published_events == [coverage]

    # CommitTranscript.rows_published retires through BoundViewHost.retire_blocks (no view.contents needed).
    retired_via_commit = []
    fake_owner = SimpleNamespace(
        paging_window=lambda: None,
        window=SimpleNamespace(scroll_revision=0),
        has_more=lambda _end: False,
        view=SimpleNamespace(retire_blocks=lambda blocks: retired_via_commit.extend(blocks) or "retired"),
    )

    async def check_commit_retirement():
        commit = CommitTranscript(
            source=SimpleNamespace(),
            owner=fake_owner,
            live_blocks=(uncovered_response,),
            claims=(block_claim(uncovered_response),),
        )
        commit.rows_published(fake_owner)
        return commit.retirement

    assert asyncio.run(check_commit_retirement()) == "retired"
    assert retired_via_commit == [uncovered_response]


def test_conversation_comms_handlers_are_shared_across_frontends_and_filter_publications():
    from agent_comms.acp_extension import (
        NativeRoundCommittedUpdate,
        PromptCancelledUpdate,
        TranscriptChangedUpdate,
    )
    from agent_comms.execution.transcript_sources import UnreadTranscriptCursor

    from toad.conversation_comms_handlers import ConversationCommsHandlers
    from toad.core.events import CommsUpdated, CoreEventStream
    from toad.qt.agent_surface import subscribe_agent
    from toad.qt.conversation import QtConversation
    from toad.qt.core_events import QtCoreObserver, QtPublication
    from toad.widgets.conversation import Conversation

    for name in (
        "accepts",
        "present_started_input",
        "on_comms_updated",
        "on_turn_changed",
        "on_queue_view_update",
        "on_input_started",
        "on_input_failed",
        "on_coordination_changed",
        "on_prompt_cancelled",
        "on_transcript_changed",
        "on_native_round_committed",
        "on_goal_changed",
        "on_compaction_changed",
        "on_compaction_end",
        "on_transcript_snapshot",
    ):
        assert getattr(Conversation, name) is getattr(ConversationCommsHandlers, name), name
        assert getattr(QtConversation, name) is getattr(ConversationCommsHandlers, name), name

    assert QtCoreObserver.consume_publication is ConversationCommsHandlers.consume_publication

    heard = []
    delivered = []

    class Receiver(ConversationCommsHandlers):
        def __init__(self, *, accept_session: bool) -> None:
            self.agent_binding = SimpleNamespace(accepts_message=lambda _msg: accept_session)
            self.turns = SimpleNamespace(owner=SimpleNamespace(accepts_update=lambda _upd: True))
            self.transcript = SimpleNamespace(
                require_commit=lambda: heard.append("commit"),
                changed=lambda cursor: heard.append(("changed", cursor)),
            )

        def post_core_callback(self, event, subscription) -> bool:
            delivered.append((self, subscription, QtPublication(event, subscription)))
            return True

        async def present_started_user_input(self, started) -> None:
            heard.append(("started", started))

        def restore_composer_draft(self, text: str) -> None:
            heard.append(("draft", text))

        def coordination_synced(self) -> None:
            heard.append("synced")

        async def present_turn_cancelled(self, feedback: str) -> None:
            heard.append(("cancelled", feedback))

    class Publisher:
        pass

    publisher = Publisher()
    stream = CoreEventStream(publisher)
    cancelled = PromptCancelledUpdate(input_state=None)
    commit_event = CommsUpdated(NativeRoundCommittedUpdate(identity=None))
    changed_event = CommsUpdated(TranscriptChangedUpdate(cursor=UnreadTranscriptCursor()))
    cancelled_event = CommsUpdated(cancelled)

    # Rejected by session-scoped accepts(): nothing dispatched.
    rejected = Receiver(accept_session=False)
    rejected_sub = subscribe_agent(rejected, stream)
    stream.publish(commit_event)
    for receiver, sub, pub in delivered:
        asyncio.run(sub.consume(receiver, pub))
    delivered.clear()
    rejected.retire_core(rejected_sub)
    assert heard == []

    # Accepted: CommsUpdated dispatches to the shared handlers.
    accepted = Receiver(accept_session=True)
    accepted_sub = subscribe_agent(accepted, stream)
    for event in (commit_event, changed_event, cancelled_event):
        stream.publish(event)
    for receiver, sub, pub in delivered:
        asyncio.run(sub.consume(receiver, pub))
    delivered.clear()
    assert heard == ["commit", ("changed", UnreadTranscriptCursor()), ("cancelled", cancelled.feedback)]

    # Closed subscription is ignored on both AgentEventSubscription and CoreObserver.consume_publication.
    heard.clear()
    accepted.retire_core(accepted_sub)
    asyncio.run(accepted_sub.consume(accepted, QtPublication(commit_event, accepted_sub)))
    asyncio.run(accepted.consume_publication(QtPublication(commit_event, accepted_sub)))
    assert heard == []


def test_model_selection_and_catalog_field_share_one_core_across_frontends():
    from dataclasses import dataclass, field as dc_field, make_dataclass
    from typing import Annotated

    from agent_comms.cli_verbs.target_fields import CatalogChoice
    from agent_comms.config_options import ModelConfigOption
    from formbridge.forms.declared_fields import DeclaredField
    from objectstate import DottedFieldPath, ObjectState
    from pyqt_reactive.forms.declared_editors import QtValueEditor
    from PySide6.QtWidgets import QApplication, QWidget

    import toad.qt.command_form  # noqa: F401
    from toad.client.command_draft import PreparedChoices
    from toad.client.model_selection import (
        CatalogChoiceSelection,
        CatalogModelField,
        ModelSelectionCore,
    )
    from toad.qt.model_selection import QtCatalogField, QtCatalogFieldSelection, QtModelChoiceDialog, QtModelSelection
    from toad.widgets.comms_command_dialog import CatalogField, CatalogFieldSelection
    from toad.widgets.model_selection import ModelSelection

    # Shared inheritance across Textual and Qt.
    assert issubclass(ModelSelection, ModelSelectionCore)
    assert issubclass(QtModelSelection, ModelSelectionCore)
    assert issubclass(CatalogField, CatalogModelField)
    assert issubclass(QtCatalogField, CatalogModelField)
    assert issubclass(CatalogFieldSelection, CatalogChoiceSelection)
    assert issubclass(QtCatalogFieldSelection, CatalogChoiceSelection)

    app = QApplication.instance() or QApplication([])

    @dataclass(frozen=True)
    class FakeParam:
        options: tuple[CatalogChoice, ...]

        @property
        def editor_declarations(self):
            return (ModelConfigOption,)

        @property
        def choices(self):
            return tuple((opt.name, opt.value) for opt in self.options)

        def choice_value(self, value):
            return value or ""

        def editor_value(self, value):
            return value

    param = FakeParam(
        options=(
            CatalogChoice(name="Claude Opus 4.6", value="anthropic/claude-opus-4-6", description="Deep reasoning"),
            CatalogChoice(name="Gemini 2.5 Pro", value="google/gemini-2.5-pro", description="Fast multimodal"),
            CatalogChoice(name="GPT-5", value="openai/gpt-5", description="General purpose"),
        )
    )
    draft_cls = make_dataclass(
        "Draft",
        [("model", Annotated[str, PreparedChoices(param)], dc_field(default="google/gemini-2.5-pro"))],
    )
    state = ObjectState(draft_cls())
    declared = DeclaredField(state, DottedFieldPath("model"))

    host = QWidget()
    host.resize(800, 600)
    host.show()
    editor = QtValueEditor.declared_for(declared)
    assert isinstance(editor, QtCatalogField)
    assert editor.text() == "Gemini 2.5 Pro"
    editor.setParent(host)

    dialog = QtModelChoiceDialog.for_catalog_field(editor, host)
    dialog.open_picker()
    app.processEvents()
    # Current model is ranked first before recents arrive.
    assert dialog.selection.option_list.count() == 3
    assert dialog.selection.option_list.item(0).data(QtModelSelection.MODEL_ID_ROLE) == "google/gemini-2.5-pro"

    # Recents override ordering via shared ModelSelectionCore.apply_recents.
    assert dialog.selection.apply_recents(dialog.selection._open_generation, "", ["openai/gpt-5"])
    assert dialog.selection.option_list.item(0).data(QtModelSelection.MODEL_ID_ROLE) == "openai/gpt-5"
    assert "recent" in dialog.selection.option_list.item(0).text()

    # Subsequence search filters via shared ModelSelectionCore.rank_models and submits selection.
    dialog.selection.search_input.setText("opus")
    assert dialog.selection.option_list.count() == 1
    assert dialog.selection.option_list.item(0).data(QtModelSelection.MODEL_ID_ROLE) == "anthropic/claude-opus-4-6"
    dialog.selection.submit()
    assert dialog.chosen == "anthropic/claude-opus-4-6"

    editor.apply_catalog_choice(dialog.chosen)
    editor.paint()
    assert state.get_resolved_value("model") == "anthropic/claude-opus-4-6"
    assert editor.text() == "Claude Opus 4.6"
    dialog.close()
    dialog.deleteLater()
    editor.deleteLater()

    # Session model selection (/model on ACP tabs) shares SessionChoiceSelection + ModelSelectionCore.
    from acp import schema
    from toad.acp.agent_configuration import ModelConfigurationSetting
    from toad.client.commands import AgentConversationCommands
    from toad.client.model_selection import SessionChoiceSelection
    from toad.conversation_comms_handlers import ConversationCommsHandlers
    from toad.qt.acp_tab import QtAcpSessionView
    from toad.qt.model_selection import QtSessionModelSelection
    from toad.widgets.conversation import Conversation
    from toad.widgets.model_switcher import SessionModelEditor

    assert issubclass(SessionModelEditor, SessionChoiceSelection)
    assert issubclass(QtSessionModelSelection, SessionChoiceSelection)
    assert Conversation.apply_model_change is ConversationCommsHandlers.apply_model_change
    assert QtAcpSessionView.apply_model_change is ConversationCommsHandlers.apply_model_change
    assert QtAcpSessionView.focus_model_choice is not AgentConversationCommands.focus_model_choice

    setting = ModelConfigurationSetting(
        option=schema.SessionConfigOptionSelect(
            id="model",
            name="Model",
            category="model",
            type="select",
            current_value="google/gemini-2.5-pro",
            options=[
                schema.SessionConfigSelectOption(value="anthropic/claude-opus-4-6", name="Claude Opus 4.6"),
                schema.SessionConfigSelectOption(value="google/gemini-2.5-pro", name="Gemini 2.5 Pro"),
            ],
        )
    )
    session_dialog = QtModelChoiceDialog.for_session(lambda: setting, "pi-agent", host)
    session_dialog.open_picker()
    app.processEvents()
    assert isinstance(session_dialog.selection, QtSessionModelSelection)
    assert session_dialog.selection.history_scope == "pi-agent"
    assert session_dialog.selection.option_list.count() == 2
    assert session_dialog.selection.option_list.item(0).data(QtModelSelection.MODEL_ID_ROLE) == "google/gemini-2.5-pro"
    session_dialog.selection.search_input.setText("opus")
    session_dialog.selection.submit()
    assert session_dialog.chosen == "anthropic/claude-opus-4-6"
    session_dialog.close()
    host.close()
    session_dialog.deleteLater()
    host.deleteLater()


def test_qt_conversation_shares_block_menu_and_line_link_dispatch_across_all_view_kinds():
    from toad.menus import CopyClipboardCommand, CopyPromptCommand, MenuConversation
    from toad.qt.acp_tab import QtAcpSessionView
    from toad.qt.conversation import QtConversation
    from toad.qt.history import QtToolTranscriptFragment, QtWireFragment
    from toad.qt.live_turn import QtLiveFragment, TranscriptFragment
    from toad.qt.mailbox_view import QtMailboxView
    from toad.qt.menu import QtMenu
    from toad.qt.window import ConversationView

    for cls in (QtConversation, ConversationView, QtMailboxView, QtAcpSessionView):
        assert issubclass(cls, MenuConversation), cls
        for name in (
            "open_block_menu",
            "_run_block_menu_command",
            "accepts_menu_owner",
            "block_clipboard_text",
            "block_prompt_text",
            "append_to_prompt",
            "open_line_link",
        ):
            assert getattr(cls, name) is getattr(QtConversation, name), (cls, name)

    for frag_cls in (QtWireFragment, TranscriptFragment, QtLiveFragment):
        assert hasattr(frag_cls, "block_menu"), frag_cls
        assert hasattr(frag_cls, "clipboard_text"), frag_cls
        assert hasattr(frag_cls, "allow_maximize"), frag_cls

    commands = QtMenu.block_commands(QtLiveFragment, ())
    command_types = {type(cmd) for cmd in commands}
    assert CopyClipboardCommand in command_types
    assert CopyPromptCommand in command_types
