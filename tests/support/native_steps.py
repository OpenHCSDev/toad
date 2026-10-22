"""Message journeys through a native session that more than one native test walks."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from agent_comms.channel_targets import ChannelTarget, ThreadTarget
from agent_comms.notification_progress import AnsweredProgress, IgnoredProgress
from toad.conversation_kind import ChannelConversation, DmConversation
from toad.core import input_events
from toad.navigation_target import DirectTarget, NavigationContext, channel_target
from toad.widgets.comms_chat import CommsChatView
from toad.notification_status import CheckedNotifications, NotificationStatus

from support.textual_steps import refresh_chat


def rows_with(chat, predicate):
    return [fragment.message for fragment in chat.message_history.fragments_in_range
            if predicate(fragment.message)]


def feedback_of(chat, sent) -> NotificationStatus:
    """The notification status drawn under the one message showing `sent`."""
    shown = [fragment.shown.status for fragment in chat.message_history.fragments_in_range
             if fragment.message.reference == sent.reference]
    assert len(shown) == 1, (sent.reference, len(shown))
    return shown[0]


async def direct_reply_feedback(native, owner_tab: str, *, body: str) -> None:
    """Send one direct message and follow it: responding while open, settled while hidden,
    answered exactly once on return, and once again after closing and reopening the tab.

    The provider's reply waits until the tab is hidden.
    """
    ui, comms, provider = native.ui, native.comms, native.provider
    target = native.thread
    app, _pilot = ui.textual
    user = comms.messaging.user_identity(str(native.project)).name
    navigation = NavigationContext(app, owner_tab, native.project, user)
    await DirectTarget(target).open(navigation)
    screen = app.selected_session
    await screen.wait_content_ready()
    chat = screen.query_one(CommsChatView)
    assert chat.conversation == DmConversation(ThreadTarget(target))
    assert not rows_with(chat, lambda message: message.body == body)
    provider.hold_next_request()
    await chat.submit_input(input_events.UserInputSubmitted(body))
    await ui.until(provider.entered.is_set, seconds=30, why="the direct message at the provider")
    await ui.until(lambda: rows_with(chat, lambda message: message.body == body), seconds=20,
                   why="the sent message in the chat")
    sent_rows = rows_with(chat, lambda message: message.body == body)
    assert len(sent_rows) == 1
    sent = sent_rows[0]
    assert sent.sender == user and sent.target == target
    await ui.until(lambda: feedback_of(chat, sent).working, seconds=20,
                   why="active delivery feedback under the sent message")
    assert comms.registry.require(target).executing

    await ui.select_tab(owner_tab)
    assert app.selected_session is not screen
    provider.release()
    await ui.until(lambda: not comms.registry.require(target).executing, seconds=20,
                   why="the reply turn to finish while the chat is hidden")
    assert app.selected_session is not screen

    def replies():
        return rows_with(chat, lambda message: message.sender == target and message.seq > sent.seq)

    await DirectTarget(target).open(navigation)
    assert app.selected_session is screen, "Returning replaced the open direct-message tab"
    await ui.until(replies, seconds=20, why="the reply in the chat")
    assert len(replies()) == 1
    reply = replies()[0]
    assert reply.target == user and reply.reference != sent.reference
    await ui.until(lambda: AnsweredProgress.label in feedback_of(chat, sent).title, seconds=20,
                   why="the answered delivery feedback")
    feedback = feedback_of(chat, sent)
    assert isinstance(feedback, CheckedNotifications)
    assert any(item.recipient == target and isinstance(item.state, AnsweredProgress)
               and item.answer == reply.reference
               for item in feedback.notifications)
    await ui.close_tab(screen.id)
    await DirectTarget(target).open(navigation)
    reopened = app.selected_session
    assert reopened is not screen and reopened.id != screen.id
    await reopened.wait_content_ready()
    fresh = reopened.query_one(CommsChatView)
    assert fresh.conversation == DmConversation(ThreadTarget(target))
    await ui.until(lambda: all(
        sum(fragment.message.reference == reference
            for fragment in fresh.message_history.fragments_in_range) == 1
        for reference in (sent.reference, reply.reference)), seconds=20,
        why="the message and its reply once each after reopening")
    await ui.until(lambda: AnsweredProgress.label in feedback_of(fresh, sent).title, seconds=20,
                   why="answered feedback after reopening")
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
    assert chat.conversation == ChannelConversation(ChannelTarget("#team"))
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
    provider.release()
    await ui.until(lambda: not comms.registry.require("beta").executing, seconds=20, why="the decision to finish")
    await refresh_chat(chat)
    await ui.until(lambda: IgnoredProgress.label in feedback_of(chat, sent).title, seconds=10,
                   why="read feedback after declining the channel message")
    feedback = feedback_of(chat, sent)
    assert isinstance(feedback, CheckedNotifications)
    assert any(item.recipient == native.thread and isinstance(item.state, IgnoredProgress)
               and item.answer is None for item in feedback.notifications)


@asynccontextmanager
async def goal_on_real_owner(workspace, objective: str, *, size=(110, 35), arrange=None):
    """A real owner (Core's ACP server in this process, no model) with an active goal, shown in Toad
    through an agent object bound to the owner's session.

    `arrange(comms, session, goal)` may change the goal on the owner before the view binds the agent.
    Yields (ui, agent, Core owner, session, goal as first set).
    """
    import os

    from agent_comms.goal_actions import SetGoalAction

    from support.native import owner_server, start_private_native_wire

    os.environ["AGENT_COMMS_AGENT_MODELS"] = "openrouter/fake"
    comms = start_private_native_wire(workspace.roots.wire)
    owner = owner_server(comms)
    try:
        session = (await owner.new_session(cwd=str(workspace.project))).session_id
        async with workspace.app(size=size) as ui:
            agent = ui.detached_agent()
            agent.coordination = comms.configuration.answer(session)
            goal = await agent.update_goal(SetGoalAction, objective)
            if arrange is not None:
                arrange(comms, session, goal)
            conversation = ui.conversation
            conversation.bind_agent(agent)
            agent.ready = True
            await conversation.goal_observation.refresh()
            await ui.step()
            yield ui, agent, owner, session, goal
    finally:
        await owner.shutdown()
