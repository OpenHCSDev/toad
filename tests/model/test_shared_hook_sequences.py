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
