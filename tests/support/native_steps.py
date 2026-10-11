"""Message journeys through a native session that more than one native test walks."""

from __future__ import annotations

import asyncio

from agent_comms.input_disposition import InputDispositions
from toad.conversation_kind import ChannelConversation, DmConversation
from toad.core import input_events
from toad.navigation_target import DirectTarget, NavigationContext, channel_target
from toad.widgets.channel_participants import ChannelParticipants
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.message_notifications import MessageNotifications

from support.textual_steps import refresh_chat


def rows_with(chat, predicate):
    return [message for message, _ in chat.message_history.rows if predicate(message)]


def feedback_of(chat, sent) -> MessageNotifications:
    """The delivery feedback drawn under the one row showing `sent`."""
    rows = [widget for message, widget in chat.message_history.rows if message.reference == sent.reference]
    assert len(rows) == 1, (sent.reference, len(rows))
    return rows[0].query_one(MessageNotifications)


async def direct_reply_feedback(native, owner_tab: str, *, hold: bool, target: str = "beta",
                                body: str = "DIRECT_NATIVE_MESSAGE",
                                reply_prefix: str | None = "NATIVE_RESPONSE_") -> None:
    """Send one direct message and follow it: responding while open, settled while hidden,
    answered exactly once on return, and once again after closing and reopening the tab.

    With `hold` the provider's reply waits until the tab is hidden.
    """
    ui, comms, provider = native.ui, native.comms, native.provider
    app, _pilot = ui.textual
    user = comms.messaging.user_identity(str(native.project)).name
    navigation = NavigationContext(app, owner_tab, native.project, user)
    await DirectTarget(target).open(navigation)
    screen = app.selected_session
    await screen.wait_content_ready()
    chat = screen.query_one(CommsChatView)
    assert chat.target == target and chat.conversation_kind is DmConversation
    assert not rows_with(chat, lambda message: message.body == body)
    if hold:
        provider.hold_next_request()
    await chat.submit_input(input_events.UserInputSubmitted(body))
    if hold:
        await ui.until(provider.entered.is_set, seconds=30, why="the direct message at the provider")
    await ui.until(lambda: rows_with(chat, lambda message: message.body == body), seconds=20,
                   why="the sent message in the chat")
    sent_rows = rows_with(chat, lambda message: message.body == body)
    assert len(sent_rows) == 1
    sent = sent_rows[0]
    assert sent.sender == user and sent.target == target
    await ui.until(lambda: "Responding" in str(feedback_of(chat, sent).title), seconds=20,
                   why="'Responding' under the sent message")
    assert comms.registry.require(target).executing

    await ui.select_tab(owner_tab)
    assert app.selected_session is not screen
    provider.release()
    await ui.until(lambda: not comms.registry.require(target).executing, seconds=20,
                   why="the reply turn to finish while the chat is hidden")
    assert app.selected_session is not screen

    def replies():
        return rows_with(chat, lambda message: message.sender == target and message.seq > sent.seq
                         and (reply_prefix is None or message.body.startswith(reply_prefix)))

    await DirectTarget(target).open(navigation)
    assert app.selected_session is screen, "Returning replaced the open direct-message tab"
    await ui.until(replies, seconds=20, why="the reply in the chat")
    assert len(replies()) == 1
    reply = replies()[0]
    assert reply.target == user and reply.reference != sent.reference
    await ui.until(lambda: "Responded" in str(feedback_of(chat, sent).title), seconds=20,
                   why="'Responded' under the sent message")
    outcomes = await asyncio.to_thread(comms.views.message_notifications, (sent,))
    assert any(item.recipient == target and item.state == "Responded"
               for item in outcomes[sent.seq, sent.message_id])
    if not hold:
        from agent_comms.input_origin import WireInputOrigin

        recipient = comms.registry.require(target)
        native_input = InputDispositions(comms.root / InputDispositions.filename).read().lookup(
            InputDispositions.bus_key(sent, recipient))
        assert native_input.has_started and native_input.matches_owner(recipient.incarnation)
        assert isinstance(native_input.origin, WireInputOrigin)
        assert native_input.origin.reference == sent.reference

    await ui.close_tab(screen.id)
    await DirectTarget(target).open(navigation)
    reopened = app.selected_session
    assert reopened is not screen and reopened.id != screen.id
    await reopened.wait_content_ready()
    fresh = reopened.query_one(CommsChatView)
    assert fresh.conversation_kind is DmConversation
    await ui.until(lambda: all(
        sum(message.reference == reference for message, _ in fresh.message_history.rows) == 1
        for reference in (sent.reference, reply.reference)), seconds=20,
        why="the message and its reply once each after reopening")
    await ui.until(lambda: "Responded" in str(feedback_of(fresh, sent).title), seconds=20,
                   why="'Responded' after reopening")
    await ui.select_tab(owner_tab)


async def channel_message_feedback(native, owner_tab: str) -> None:
    """Send one channel message the thread declines: it shows as active while it decides,
    idle afterwards, and the message is marked checked with no response."""
    ui, comms, provider = native.ui, native.comms, native.provider
    app, _pilot = ui.textual
    user = comms.messaging.user_identity(str(native.project)).name
    await channel_target("#team").open(NavigationContext(app, owner_tab, native.project, user))
    await app.selected_session.wait_content_ready()
    chat = app.selected_session.query_one(CommsChatView)
    assert chat.target == "#team" and chat.conversation_kind is ChannelConversation
    provider.hold_next_request()
    await chat.submit_input(input_events.UserInputSubmitted("CHANNEL_NATIVE_TRIAGE"))
    await ui.until(provider.entered.is_set, seconds=30, why="the triage question at the provider")
    await ui.until(lambda: rows_with(chat, lambda message: message.body == "CHANNEL_NATIVE_TRIAGE"),
                   seconds=20, why="the sent message in the channel")
    sent_rows = rows_with(chat, lambda message: message.body == "CHANNEL_NATIVE_TRIAGE")
    assert len(sent_rows) == 1
    sent = sent_rows[0]
    await ui.until(lambda: comms.registry.require("beta").executing, seconds=20, why="the thread to be deciding")
    await refresh_chat(chat)
    await ui.step()
    roster = chat.query_one(ChannelParticipants)
    assert "beta" in roster.names.render().plain, roster.names.render()
    assert roster in app.screen._compositor.visible_widgets
    provider.release()
    await ui.until(lambda: not comms.registry.require("beta").executing, seconds=20, why="the decision to finish")
    await refresh_chat(chat)
    await ui.until(lambda: "No active turns" in roster.names.render().plain, seconds=20, why="an idle roster")
    notification = feedback_of(chat, sent)
    await ui.until(lambda: "Checked" in str(notification.title), seconds=10, why="'Checked' under the message")
    assert "no response" in str(notification.title).lower(), notification.title
