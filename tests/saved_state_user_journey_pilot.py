"""Continuous saved-state journey on installed App/ACP/Pi, using actual clicks."""

import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path

from acp.schema import TextContentBlock
from agent_comms.acp import CommsClient
from agent_comms.acp_extension import RequestFailedUpdate, decode_updates
from agent_comms.threads import Thread
from l0a_native_installed_pilot import main as native_fixture
from l0a_native_installed_pilot import until
from native_session_retention_pilot import InstalledApp, conversation_paint
from runtime_fixture import wait_channel_roster
from textual.widgets import Input
from viewport_recent_tabs_pilot import settled

from toad.screens.comms import CommsScreen
from toad.thread_actions import ForkAction
from toad.widgets.channel_participants import ChannelParticipants
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.comms_fork_dialog import ForkDialog
from toad.widgets.comms_menu import ContextMenuItem
from toad.widgets.comms_sidebar import ChannelGroup, CommsRow
from toad.widgets.message_notifications import MessageNotifications
from toad.widgets.session_tabs import SessionLabel


class SavedStateSubscriber:
    """Observe real ACP failures while producing representative native history."""

    def __init__(self):
        self.failures = []

    def require_success(self):
        assert not self.failures, "\n".join(failure.feedback for failure in self.failures)

    async def session_update(self, **kwargs):
        for fact in decode_updates(kwargs["update"].get("_meta")):
            if isinstance(fact, RequestFailedUpdate):
                self.failures.append(fact.failure)


async def prepare_saved_state(comms, project, requests, entered, release, hold_next):
    release.set()
    client = CommsClient(
        comms, runtime_enabled=True,
        private_nk_native_package=Path(os.environ["AC_NATIVE_COPIED_PACKAGE"]),
        private_nk_wire_root_id=os.environ["AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID"],
    )
    subscriber = SavedStateSubscriber()
    client.on_connect(subscriber)
    try:
        await client.load_session(cwd=str(project), session_id="beta")
        for number in range(2):
            prompt = f"SAVED_READER_{number}\n\n" + "\n\n".join(
                f"Retained reader paragraph {row}: actual native history." for row in range(12)
            )
            async with asyncio.timeout(20):
                await client.prompt("beta", [TextContentBlock(type="text", text=prompt)])
            subscriber.require_success()
        assert len(requests) == 2, "Saved-state preparation must reach the actual provider"
        native = Path(comms.registry.require("beta").session_file)
        assert "SAVED_READER_0" in native.read_text()
    finally:
        await client.shutdown()

    comms.messaging.send("beta", "#team", "SAVED_CHANNEL_MESSAGE")
    comms.threads.register(Thread(
        "gamma", frozenset({"team"}), str(project),
        model="selected-offline/fixture", thinking_level="off",
    ))
    await asyncio.to_thread(comms.owners.start, "gamma")
    print("PREPARED_REAL_NATIVE_SAVED_HISTORY_AND_CHANNEL", len(requests), flush=True)


def screen_paint(app):
    return "\n".join(strip.text for strip in app.screen._compositor.render_strips())


async def click_tab(app, pilot, session_id):
    tab = next(label for label in app.screen.query(SessionLabel) if label.id == session_id)
    tab.scroll_visible(animate=False, immediate=True)
    await pilot.pause()
    assert await pilot.click(tab), f"Tab {session_id} was not physically clickable"
    await until(pilot, lambda: app.selected_session.id == session_id)


async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    first = app.selected_session
    await until(pilot, lambda: "NATIVE_RESPONSE_2" in conversation_paint(app.screen))
    assert "SAVED_READER_1" in conversation_paint(app.screen)
    print("SAVED_HISTORY_STARTUP_ACTUAL_PAINT", flush=True)
    sidebar = await wait_channel_roster(app, pilot, "#team")
    channel_row = next(row for row in sidebar.query(CommsRow) if row.target_name == "#team")
    channel_row.scroll_visible(animate=False, immediate=True)
    await pilot.pause()
    assert await pilot.click(channel_row), "Channel-bar row was not physically clickable"
    await until(pilot, lambda: isinstance(app.selected_session, CommsScreen))
    channel = app.selected_session
    await until(pilot, lambda: bool(channel.query(CommsChatView)))
    await until(pilot, lambda: "SAVED_CHANNEL_MESSAGE" in screen_paint(app))
    print("CHANNEL_BAR_CLICK_COMMS_SCREEN_SAVED_HISTORY_PAINT", flush=True)
    await click_tab(app, pilot, first.id)
    await until(pilot, lambda: "NATIVE_RESPONSE_2" in conversation_paint(app.screen))
    assert len(requests) == 2, "Channel/tab navigation replayed an input"
    print("SAVED_CHANNEL_AGENT_RETURN_NO_REPLAY", flush=True)
    await unopened_participant(app, pilot, comms, channel, entered, release, hold_next, requests)
    await clicked_reader_editor_return(app, pilot, first)
    await fork_and_first_input(app, pilot, comms, first, entered, release, hold_next, requests)
    await channel_reply_feedback(app, pilot, comms, channel, first, entered, release,
                                 hold_next, requests)


async def submit_editor(pilot, editor, text):
    editor.scroll_visible(animate=False, immediate=True)
    await pilot.pause()
    assert await pilot.click(editor), "Native composer was not physically clickable"
    editor.insert(text)
    await pilot.press("enter")


async def click_thread(app, pilot, name, channel_name="#team"):
    sidebar = await wait_channel_roster(app, pilot, channel_name)
    group = next(group for group in sidebar.query(ChannelGroup)
                 if group.row.target_name == channel_name)
    if group.expanded is False:
        assert await pilot.click(group.disclosure)
        await pilot.pause()
    await until(pilot, lambda: any(row.target_name == name for row in group.member_rows))
    row = next(row for row in group.member_rows if row.target_name == name)
    row.scroll_visible(animate=False, immediate=True)
    await pilot.pause()
    previous = app.selected_session
    assert await pilot.click(row), f"Unopened thread {name} was not physically clickable"
    await until(pilot, lambda: app.selected_session is not previous)
    await app.selected_session.wait_content_ready()
    await until(pilot, lambda: app.selected_session.conversation.agent_ready)
    assert app.selected_session.conversation.agent.session_id == name
    return app.selected_session


async def unopened_participant(app, pilot, comms, channel, entered, release, hold_next, requests):
    gamma = await click_thread(app, pilot, "gamma")
    print("UNOPENED_THREAD_PHYSICAL_CLICK_ACTUAL_ATTACHMENT", flush=True)
    entered.clear()
    release.clear()
    hold_next.set()
    prompt = "JOURNEY_GAMMA_INPUT\n\n" + "\n\n".join(
        f"Gamma retained reader paragraph {row}: native journal content." for row in range(24)
    )
    await submit_editor(pilot, gamma.conversation.prompt.prompt_text_area, prompt)
    await until(pilot, entered.is_set)
    assert comms.registry.require("gamma").executing
    await click_tab(app, pilot, channel.id)
    participants = channel.query_one(ChannelParticipants)
    await until(pilot, lambda: "gamma" in participants.names.render().plain)
    names = participants.names
    offset = names.render().plain.index("gamma") + 1
    assert await pilot.click(names, offset=(offset, 0)), "Participant link not physically clickable"
    await until(pilot, lambda: app.selected_session is gamma)
    print("CHANNEL_ACTIVE_PARTICIPANT_CLICK_SAME_NATIVE_TAB", flush=True)
    release.set()
    try:
        await until(pilot, lambda: "NATIVE_RESPONSE_3" in conversation_paint(app.screen))
    except TimeoutError:
        view = gamma.conversation
        print("PARTICIPANT_RETURN_READER", {
            "selected": app.selected_session.id,
            "native_session": view.agent.session_id,
            "executing": comms.registry.require("gamma").executing,
            "scroll_y": view.window.scroll_y,
            "max_scroll_y": view.window.max_scroll_y,
            "follows_tail": view.window.follows_tail,
            "provider_calls": len(requests),
        }, flush=True)
        evidence = Path(os.environ["L0A_EVIDENCE"])
        (evidence / "participant-return-painted.txt").write_text(conversation_paint(app.screen))
        (evidence / "participant-return.svg").write_text(app.export_screenshot())
        raise
    await until(pilot, lambda: comms.registry.require("gamma").executing is False)
    assert len(requests) == 3


@dataclass
class ReaderCheckpoint:
    source: object
    document: object
    history: object
    reader_y: float
    painted: str

    @classmethod
    async def capture(cls, source, app, pilot):
        view = source.conversation
        await settled(pilot, view)
        await until(pilot, lambda: view.window.max_scroll_y > 0)
        view.window.release_anchor()
        view.window.scroll_to(y=min(5, view.window.max_scroll_y - 1),
                              animate=False, immediate=True)
        await settled(pilot, view)
        assert view.window.follows_tail is False
        editor = view.prompt.prompt_text_area
        editor.insert("draft-" + source.id)
        editor.history.checkpoint()
        editor.insert(" with undo")
        return cls(source, editor.document, editor.history, view.window.scroll_y,
                   conversation_paint(app.screen))

    async def verify(self, app, pilot):
        view = self.source.conversation
        await settled(pilot, view)
        editor = view.prompt.prompt_text_area
        assert editor.document is self.document
        assert editor.history is self.history
        assert editor.text == "draft-" + self.source.id + " with undo"
        assert view.window.scroll_y == self.reader_y
        assert conversation_paint(app.screen) == self.painted


async def clicked_reader_editor_return(app, pilot, first):
    second = app.selected_session
    checkpoints = []
    for source in (first, second):
        await click_tab(app, pilot, source.id)
        checkpoints.append(await ReaderCheckpoint.capture(source, app, pilot))
    for checkpoint in (*checkpoints, checkpoints[0]):
        await click_tab(app, pilot, checkpoint.source.id)
        await checkpoint.verify(app, pilot)
    for checkpoint in checkpoints:
        await click_tab(app, pilot, checkpoint.source.id)
        editor = checkpoint.source.conversation.prompt.prompt_text_area
        editor.undo()
        assert editor.text == "draft-" + checkpoint.source.id
    await click_tab(app, pilot, first.id)
    print("CLICKED_ABA_SAVED_READER_DOCUMENT_HISTORY_DRAFT_UNDO_PRESERVED", flush=True)


async def fork_and_first_input(app, pilot, comms, first, entered, release, hold_next, requests):
    parent_path = Path(comms.registry.require("beta").session_file)
    original = parent_path.read_bytes()
    before = len(requests)
    sidebar = await wait_channel_roster(app, pilot, "#team")
    row = next(row for row in sidebar.query(CommsRow) if row.target_name == "beta")
    row.scroll_visible(animate=False, immediate=True)
    await pilot.pause()
    assert await pilot.click(row, button=3)
    await until(pilot, lambda: bool(app.screen.query(ContextMenuItem)))
    fork = next(item for item in app.screen.query(ContextMenuItem)
                if item.action == ForkAction.declared_name)
    assert await pilot.click(fork)
    await until(pilot, lambda: isinstance(app.screen, ForkDialog))
    entry = app.screen.query_one(Input)
    assert await pilot.click(entry)
    entry.value = "journey-child JOURNEY_FORK_INPUT"
    entered.clear()
    release.clear()
    hold_next.set()
    await pilot.press("enter")
    await until(pilot, lambda: "journey-child" in comms.registry.all_threads())
    # This physical opening now races normal startup instead of following the
    # first answer. The real provider is held; no owner/PID state is fabricated.
    child_view = await click_thread(app, pilot, "journey-child", "#any")
    await until(pilot, entered.is_set)
    assert comms.registry.require("journey-child").executing
    assert f"NATIVE_RESPONSE_{before + 1}" not in conversation_paint(app.screen)
    assert parent_path.read_bytes() == original
    print("FORK_IMMEDIATE_PHYSICAL_OPEN_REAL_ATTACHMENT_BEFORE_FIRST_NATIVE_ANSWER", flush=True)
    release.set()
    await until(pilot, lambda: len(requests) == before + 1)
    await until(pilot, lambda: comms.registry.require("journey-child").executing is False)
    child = comms.registry.require("journey-child")
    assert parent_path.read_bytes() == original
    native = Path(child.session_file).read_text()
    rows = [json.loads(line) for line in native.splitlines()]
    users = [row["message"] for row in rows
             if row["type"] == "message" and row["message"]["role"] == "user"]
    assert sum("JOURNEY_FORK_INPUT" in json.dumps(row["content"]) for row in users) == 1
    assert f"NATIVE_RESPONSE_{before + 1}" in native
    assert sum(row["type"] == "compaction" for row in rows) == 0
    assert len(requests) == before + 1, "Fork input replayed"
    print("PHYSICAL_FORK_DIALOG_NORMAL_NATIVE_FIRST_ANSWER_PARENT_PRESERVED", flush=True)
    assert app.selected_session is child_view
    await until(pilot, lambda: f"NATIVE_RESPONSE_{before + 1}" in conversation_paint(app.screen))
    assert len(requests) == before + 1, "Opening the fork replayed its first input"
    assert parent_path.read_bytes() == original
    print("FORK_FIRST_OPEN_SAVED_NATIVE_ANSWER_ACTUAL_PAINT_NO_REPLAY", flush=True)
    await click_tab(app, pilot, first.id)


async def channel_reply_feedback(app, pilot, comms, channel, first, entered, release,
                                 hold_next, requests):
    await click_tab(app, pilot, channel.id)
    chat = channel.query_one(CommsChatView)
    before = len(requests)
    entered.clear()
    release.clear()
    hold_next.set()
    await submit_editor(pilot, chat.prompt.prompt_text_area, "@gamma JOURNEY_CHANNEL_QUESTION")
    await until(pilot, entered.is_set)
    participants = chat.query_one(ChannelParticipants)
    await until(pilot, lambda: "gamma" in participants.names.render().plain)
    assert comms.registry.require("gamma").executing
    await until(pilot, lambda: "Responding" in screen_paint(app))
    print("CHANNEL_NOTIFICATION_ACTUAL_NATIVE_WORKING_STATUS", flush=True)
    release.set()
    await until(pilot, lambda: f"NATIVE_RESPONSE_{before + 1}" in screen_paint(app))
    await until(pilot, lambda: any("Responded" in str(feedback.title)
                                 for feedback in chat.query(MessageNotifications)))
    feedback = next(feedback for feedback in chat.query(MessageNotifications)
                    if "Responded" in str(feedback.title))
    title = feedback.query_one("CollapsibleTitle")
    title.scroll_visible(animate=False, immediate=True)
    await pilot.pause()
    assert await pilot.click(title), "Notification disclosure was not physically clickable"
    await until(pilot, lambda: "gamma: Responded" in screen_paint(app))
    print("CHANNEL_RESPONDED_NOTIFICATION_DISCLOSURE_ACTUAL_PAINT", flush=True)
    await until(pilot, lambda: len(requests) == before + 2)
    await until(pilot, lambda: comms.registry.require("beta").executing is False)
    await until(pilot, lambda: comms.registry.require("gamma").executing is False)
    assert "JOURNEY_CHANNEL_QUESTION" in str(requests[before]["messages"])
    assert f"NATIVE_RESPONSE_{before + 1}" in str(requests[-1]["messages"])
    await click_tab(app, pilot, first.id)
    await click_tab(app, pilot, channel.id)
    await until(pilot, lambda: f"NATIVE_RESPONSE_{before + 1}" in screen_paint(app))
    await pilot.pause(1.2)
    assert len(requests) == before + 2, "Reply caused replay or unbounded ping-pong"
    print("CHANNEL_REPLY_SAVED_HISTORY_AUTOMATIC_AUTHOR_NATIVE_OBSERVATION_NO_REPLAY", flush=True)


if __name__ == "__main__":
    asyncio.run(native_fixture(
        app_type=InstalledApp, prepare_state=prepare_saved_state, acceptance=acceptance,
    ))
