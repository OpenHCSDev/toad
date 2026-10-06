"""Continuous saved-state journey on installed App/ACP/Pi, using actual clicks."""

import asyncio
import hashlib
import json
import os
import shlex
import sys
import traceback
from pathlib import Path
from weakref import ref

from acp.schema import SessionNotification, TextContentBlock
from agent_comms.acp import CommsClient
from agent_comms.acp_extension import RequestFailedUpdate, decode_updates
from agent_comms.threads import Thread
from l0a_native_installed_pilot import main as native_fixture
from l0a_native_installed_pilot import (
    selected_triage_reply, until, message_feedback, direct_reply_feedback, response_painted,
)
from native_session_retention_pilot import InstalledApp, conversation_paint
from runtime_fixture import wait_channel_roster, wait_fork_dialog
from textual.widgets import Input
from viewport_recent_tabs_pilot import ReaderCheckpoint, settled

from toad.screens.comms import CommsScreen
from agent_comms.cli_commands import ForkCliCommand
from toad.widgets.channel_participants import ChannelParticipants
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.comms_menu import ContextMenuItem
from toad.widgets.comms_sidebar import ChannelGroup, CommsRow
from toad.widgets.session_tabs import SessionLabel
from toad.widgets.agent_response import AgentResponse
from toad.widgets.transcript_history import TranscriptFragmentView
from toad.widgets.presentation_window import StationaryPreparation
from toad.widgets.message_divider import MessageDivider


# 2,800 characters / forty characters per SSE delta = 70 native chunks. Only
# the first gamma reply is long, keeping the rest of the continuous journey small.
_reply_body = "NATIVE_RESPONSE_3\n\n" + "\n\n".join(
    f"Streamed paragraph {row}: the native owner delivers one continuous answer. "
    "Queued UI events must retain the response identity captured at ACP ingress."
    for row in range(20)
)
_reply_end = "\n\nSTREAM_REPLY_END_3\n"
STREAM_REPLY = _reply_body[:2800 - len(_reply_end)] + _reply_end
assert len(STREAM_REPLY) == 2800


def streamed_reply(request, number):
    content = STREAM_REPLY if number == 3 else f"NATIVE_RESPONSE_{number}"
    return selected_triage_reply(request) or {"role": "assistant", "content": content}, "stop"


class StreamJourneyApp(InstalledApp):
    """Observe every composited frame, including transient and saved headers."""
    stream_view = None

    def observe_stream(self, view):
        self.stream_view = view
        self.stream_frames = []
        self.stream_live_blocks = set()
        self.stream_violations = []

    def _display(self, screen, renderable):
        super()._display(screen, renderable)
        view = self.stream_view
        if (view is None or renderable is None or self._batch_count
                or screen is not self.screen or self.selected_session.conversation is not view):
            return
        viewport = view.window.scrollable_content_region
        visible = screen._compositor.visible_widgets
        blocks = [block for block in view.query(AgentResponse)
                  if block in visible and block.region.overlaps(viewport)]
        live = [block for block in blocks
                if not isinstance(block.parent, TranscriptFragmentView)]
        # Weak references preserve observations without retaining retired bodies.
        self.stream_live_blocks.update(ref(block) for block in live)
        headers = [header for block in blocks for header in block.query(MessageDivider)
                   if header in visible and header.region.overlaps(viewport)]
        frame = {
            "frame": len(self.stream_frames), "headers": len(headers),
            "live_response_identities": len(self.stream_live_blocks),
            "response_lengths": [len(block.source) for block in blocks],
            "busy": view.turns.owner.busy,
        }
        self.stream_frames.append(frame)
        if len(headers) > 1 or len(self.stream_live_blocks) > 1:
            self.stream_violations.append(frame)
            if len(self.stream_violations) == 1:
                evidence = Path(os.environ["L0A_EVIDENCE"])
                (evidence / "first-duplicate-header.txt").write_text(conversation_paint(screen))
                (evidence / "first-duplicate-header.svg").write_text(self.export_screenshot())

    def require_continuous_stream(self):
        evidence = Path(os.environ["L0A_EVIDENCE"])
        (evidence / "stream-frames.json").write_text(json.dumps(self.stream_frames, indent=2))
        assert not self.stream_violations, (
            "One native reply created multiple painted Agent headers", self.stream_violations[:3]
        )
        assert self.stream_frames and max(frame["headers"] for frame in self.stream_frames) == 1
        assert len(self.stream_live_blocks) == 1, "The journey never painted a live response"
        print("EVERY_STREAM_FRAME_ONE_CONTINUOUS_RESPONSE", {
            "characters": len(STREAM_REPLY), "sse_chunks": 70,
            "frames": len(self.stream_frames), "live_response_identities": 1,
            "max_visible_headers": 1,
        }, flush=True)
        self.stream_view = None
from toad.widgets.side_bar import SideBar
from toad.widgets.thread_comms import ThreadCommsSidebar


class SavedStateSubscriber:
    """Observe real ACP failures while producing representative native history."""

    def __init__(self):
        self.failures = []

    def require_success(self):
        assert not self.failures, "\n".join(failure.feedback for failure in self.failures)

    async def session_update(self, **kwargs):
        notification = SessionNotification.model_validate({
            "sessionId": kwargs["session_id"], "update": kwargs["update"],
        }, strict=True)
        for fact in decode_updates(notification.update.field_meta):
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
    comms.registry.declare(Thread(
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
    assert await pilot.click(tab, offset=(tab.size.width // 2, 0)), f"Tab {session_id} was not physically clickable"
    await until(pilot, lambda: app.selected_session.id == session_id)


async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests,
                     *, warm_only=False):
    first = app.selected_session
    await until(pilot, lambda: "NATIVE_RESPONSE_2" in conversation_paint(app.screen))
    assert "SAVED_READER_1" in conversation_paint(app.screen)
    print("SAVED_HISTORY_STARTUP_ACTUAL_PAINT", flush=True)
    await independent_source_publication(agent, comms)
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
    try:
        await until(pilot, lambda: "NATIVE_RESPONSE_2" in conversation_paint(app.screen))
    except TimeoutError:
        ReaderCheckpoint.record_failed_reader(first, app)
        raise
    assert len(requests) == 2, "Channel/tab navigation replayed an input"
    print("SAVED_CHANNEL_AGENT_RETURN_NO_REPLAY", flush=True)
    gamma = await unopened_participant(app, pilot, comms, channel, entered, release, hold_next, requests)
    sidebar = await wait_channel_roster(app, pilot, "#team")
    row = next(row for row in sidebar.query(CommsRow) if row.target_name == "#team")
    row.scroll_visible(animate=False, immediate=True)
    await pilot.pause()
    assert await pilot.click(row)
    await until(pilot, lambda: app.selected_session is channel)
    assert sum(isinstance(app.workspace_sessions.require(entry.mode), CommsScreen)
               for entry in app.session_navigation.members) == 1
    print("SAME_CHANNEL_FROM_SECOND_AGENT_REUSES_ONE_EXISTING_TAB", flush=True)
    await click_tab(app, pilot, gamma.id)
    await clicked_reader_editor_return(app, pilot, first)
    if warm_only:
        return
    await adaptive_reader_journey(app, pilot, requests)
    await fork_and_first_input(app, pilot, comms, first, entered, release, hold_next, requests)
    await channel_reply_feedback(app, pilot, comms, channel, first, entered, release,
                                 hold_next, requests, gamma)
    await direct_reply_feedback(pilot, app, comms, first.id, app.project_dir,
                                entered, release, hold_next)


async def independent_source_publication(agent, comms):
    """A real status-store writer cannot monopolize the native read binding."""
    from agent_comms.goal_waits import GoalWaits

    observation = None
    try:
        with GoalWaits(comms.root / GoalWaits.filename).locked():
            observation = asyncio.create_task(agent.get_thread_presentation())
            await asyncio.sleep(.2)
            assert not observation.done(), "Actual held status read did not wait for its store"
            page = await asyncio.wait_for(agent.get_transcript_page(), 3)
            assert page.events and page.after.session_file
            assert not observation.done(), "Status-store lock was released prematurely"
            print("ACTUAL_NATIVE_PAGE_DELIVERED_WHILE_STATUS_STORE_HELD", flush=True)
    finally:
        if observation is not None:
            await observation


async def prepare_editor(pilot, editor, text):
    """Reveal and physically focus the original composer before submission."""
    editor.scroll_visible(animate=False, immediate=True)
    await pilot.pause()
    assert await pilot.click(editor), "Native composer was not physically clickable"
    editor.insert(text)


async def submit_editor(pilot, editor, text):
    await prepare_editor(pilot, editor, text)
    await pilot.press("enter")


async def reveal_thread_row(app, pilot, name, channel_name="#team"):
    """Physically reveal one channel's member before any pointer action."""
    sidebar = await wait_channel_roster(app, pilot, channel_name)
    group = next(group for group in sidebar.query(ChannelGroup)
                 if group.row.target_name == channel_name)
    if group.expanded is False:
        assert await pilot.click(group.disclosure)
        await pilot.pause()
    await until(pilot, lambda: any(row.target_name == name for row in group.member_container.children))
    row = next(row for row in group.member_container.children if row.target_name == name)
    row.scroll_visible(animate=False, immediate=True)
    await pilot.pause()
    assert row.is_attached and group.expanded
    assert app.screen.get_widget_at(*row.region.offset)[0] is row, (
        'Revealed channel member is not the native pointer target', name, channel_name, row.region)
    return row


async def click_thread(app, pilot, name, channel_name="#team"):
    row = await reveal_thread_row(app, pilot, name, channel_name)
    previous = app.selected_session
    assert await pilot.click(row), f"Unopened thread {name} was not physically clickable"
    await until(pilot, lambda: app.selected_session is not previous)
    await app.selected_session.wait_content_ready()
    await until(pilot, lambda: app.selected_session.conversation.agent_ready)
    assert app.selected_session.conversation.agent.session_id == name
    return app.selected_session


async def click_participant(app, pilot, participants, name):
    """Click the participant's original action in the published native cells."""
    names = participants.names

    def action_cell():
        geometry = app.screen._compositor.visible_widgets.get(names)
        if geometry is None:
            return None
        bounds, clip = geometry
        exposed = bounds.intersection(clip).intersection(app.screen.size.region)
        for y in range(exposed.y, exposed.bottom):
            for x in range(exposed.x, exposed.right):
                if (app.screen.get_style_at(x, y).meta.get("@click")
                        == ("open_thread", (name,))):
                    return x, y
        return None

    await until(pilot, lambda: action_cell() is not None)
    cell = action_cell()
    assert cell is not None, ("Participant action left the native frame", name)
    assert app.screen.get_widget_at(*cell)[0] is names
    print("PARTICIPANT_NATIVE_ACTION_CELL", name, cell,
          app.screen.get_style_at(*cell).meta.get("@click"), flush=True)
    assert await pilot.click(names, offset=(cell[0] - names.region.x,
                                          cell[1] - names.region.y)), (
        "Participant link not physically clickable", name, cell,
    )


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
    await click_participant(app, pilot, participants, "gamma")
    await until(pilot, lambda: app.selected_session is gamma)
    print("CHANNEL_ACTIVE_PARTICIPANT_CLICK_SAME_NATIVE_TAB", flush=True)
    app.observe_stream(gamma.conversation)
    release.set()
    try:
        await until(pilot, lambda: app.stream_violations
                    or "STREAM_REPLY_END_3" in conversation_paint(app.screen))
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
    if app.stream_violations:
        app.require_continuous_stream()
    await until(pilot, lambda: comms.registry.require("gamma").executing is False)
    await pilot.pause(.3)
    app.require_continuous_stream()
    assert len(requests) == 3
    return gamma


async def clicked_reader_editor_return(app, pilot, first):
    second = app.selected_session
    checkpoints = []
    try:
        for source in (first, second):
            await click_tab(app, pilot, source.id)
            view = source.conversation
            await settled(pilot, view)
            try:
                await until(pilot, lambda: view.window.max_scroll_y > 0)
            except TimeoutError:
                ReaderCheckpoint.record_failed_reader(source, app)
                raise
            view.window.release_anchor()
            view.window.scroll_to(y=min(5, view.window.max_scroll_y - 1),
                                  animate=False, immediate=True)
            await settled(pilot, view)
            assert view.window.follows_tail is False
            editor = view.prompt.prompt_text_area
            editor.insert("draft-" + source.id)
            editor.history.checkpoint()
            editor.insert(" with undo")
            checkpoints.append(await ReaderCheckpoint.capture(source, app, pilot))
        raw_reads = []
        for checkpoint in (*checkpoints, checkpoints[0]):
            before = await checkpoint.page_reads()
            await click_tab(app, pilot, checkpoint.source.id)
            await checkpoint.verify(app, pilot)
            raw_reads.append(await checkpoint.page_reads() - before)
        assert raw_reads == [0, 0, 0], ("Already-loaded source repeated raw page reads", raw_reads)
        print("CLICKED_ABA_CANONICAL_RAW_PAGE_READ_COUNTS", raw_reads, flush=True)
        for checkpoint in checkpoints:
            await click_tab(app, pilot, checkpoint.source.id)
            editor = checkpoint.source.conversation.prompt.prompt_text_area
            editor.undo()
            assert editor.text == "draft-" + checkpoint.source.id
        await click_tab(app, pilot, first.id)
        print("CLICKED_ABA_SAVED_READER_DOCUMENT_HISTORY_DRAFT_UNDO_PRESERVED", flush=True)

    finally:
        # Keep genuine identity witnesses through final warm/Undo assertions.
        # Function exit releases loop-local witnesses before the next journey.
        checkpoints.clear()


async def adaptive_reader_journey(app, pilot, requests, *,
                                  tail_text="NATIVE_RESPONSE_2", input_count=None):
    """Drive the real selected viewport; observe its existing adaptive owner."""
    if input_count is None:
        input_count = lambda: len(requests)
    view = app.selected_session.conversation
    window = view.window
    lookahead = window.document_viewport.lookahead
    samples = []
    window.watch(window, "scroll_y", lambda y: samples.append(
        (y, lookahead.travel_rows, lookahead.ahead_rows(window.size.height))), init=False)
    window.release_anchor()
    window.focus(scroll_visible=False)
    await pilot.pause(.2)
    slow_start = len(samples)
    await pilot.press("down")
    await pilot.pause(.2)
    await pilot.press("down")
    await pilot.pause(.2)
    slow = samples[slow_start:]
    assert len(slow) > 0, "Slow key scrolling did not move the real native reader"
    fast_start = len(samples)
    await pilot.press("pagedown", "pagedown")
    await pilot.pause(.1)
    fast = samples[fast_start:]
    assert len(fast) > 0, "Fast key scrolling did not move the real native reader"
    assert max(sample[2] for sample in fast) > max(sample[2] for sample in slow), (
        "Measured fast travel did not expand preparation beyond slow travel", slow, fast,
    )
    reverse_start = len(samples)
    await pilot.press("pageup")
    await pilot.pause(.1)
    reverse = samples[reverse_start:]
    assert any(sample[1] < 0 for sample in reverse), (
        "Reverse scrolling did not reverse the existing preparation owner", reverse,
    )
    assert lookahead.preparation_count(window.size.height) <= app.preparation.max_entries
    await pilot.press("end")
    await until(pilot, lambda: window.follows_tail)
    await until(pilot, lambda: tail_text in conversation_paint(app.screen))
    await settled(pilot, view)
    for _ in range(4):
        await pilot.press("pagedown")
        await settled(pilot, view)
        assert window.scroll_y <= window.max_scroll_y
        assert tail_text in conversation_paint(app.screen), (
            "Scrolling past the saved tail exposed empty history", window.scroll_y,
            window.max_scroll_y, conversation_paint(app.screen),
        )
    await until(pilot, lambda: isinstance(lookahead.demand, StationaryPreparation))
    await until(pilot, lambda: len(app.preparation._pending) == 0)
    before = app.preparation.misses, input_count()
    import sys
    idle_work = {}
    def trace_idle_work(frame, event, arg):
        if event == "call" and frame.f_code.co_name == "_execute" and "work" in frame.f_locals:
            work = frame.f_locals["work"]
            from toad.work_preparation import ContentAddressedWork
            idle_work[id(work)] = (type(work).__name__, repr(work.inputs)[:5000], repr(work)[:5000]) if isinstance(work, ContentAddressedWork) else (type(work).__name__, "scoped")
    previous_profile = sys.getprofile()
    sys.setprofile(trace_idle_work)
    try:
        await pilot.pause(1.2)
    finally:
        sys.setprofile(previous_profile)
    after = app.preparation.misses, input_count()
    print("ACTUAL_IDLE_PREPARATION_CENSUS", {"before": before, "after": after,
          "work": list(idle_work.values()), "pending": len(app.preparation._pending)}, flush=True)
    assert after == before, ("Idle reader kept preparing or replaying", before, after, idle_work)
    assert len(app.preparation._pending) == 0
    assert app.preparation.retained_bytes <= app.preparation.max_bytes
    assert len(app.preparation._ready) <= app.preparation.max_entries
    assert lookahead.ahead_rows(window.size.height) == lookahead.budget.runway_rows(window.size.height)
    print("REAL_SLOW_FAST_REVERSE_END_IDLE_PREPARATION_BOUNDED", {
        "slow": slow, "fast": fast, "reverse": reverse,
        "retained_bytes": app.preparation.retained_bytes,
        "pending": len(app.preparation._pending),
    }, flush=True)


async def prepare_fork_dialog(app, pilot, comms, parent_name, channel_name,
                              child_name, task, tags):
    """Acquire the original native CLI dialog through the actual sidebar row."""
    sidebar = await wait_channel_roster(app, pilot, channel_name)
    row = next(row for row in sidebar.query(CommsRow) if row.target_name == parent_name)
    row.scroll_visible(animate=False, immediate=True)
    await pilot.pause()
    assert await pilot.click(row, button=3)
    await until(pilot, lambda: bool(app.screen.query(ContextMenuItem)))
    fork = next(item for item in app.screen.query(ContextMenuItem)
                if item.action == ForkCliCommand.declared_name)
    assert await pilot.click(fork)
    dialog = await wait_fork_dialog(app, pilot)
    entry = dialog.query_one("#command-field-name", Input)
    assert await pilot.click(entry)
    entry.value = child_name
    supplied_tags = ForkCliCommand.editor_arguments({
        "tags": app.screen.query_one("#command-field-tags", Input).value,
    })['tags']
    assert frozenset(supplied_tags) == comms.registry.require(parent_name).tags
    from textual.widgets import TextArea
    dialog.query_one("#command-field-task", TextArea).text = task
    app.screen.query_one("#command-field-tags", Input).value = tags


async def fork_and_first_input(app, pilot, comms, first, entered, release, hold_next, requests):
    parent_path = Path(comms.registry.require("beta").session_file)
    original = parent_path.read_bytes()
    before = len(requests)
    await prepare_fork_dialog(app, pilot, comms, "beta", "#team",
                              "journey-child", "JOURNEY_FORK_INPUT", "refactor")
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
    assert child.tags == frozenset({"refactor"}), child.tags
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
    right = child_view.query_one("#thread-sidebar", SideBar)
    right.reveal()
    await until(pilot, lambda: child_view.query_one_optional(ThreadCommsSidebar) is not None)
    relationships = child_view.query_one(ThreadCommsSidebar)
    await until(pilot, lambda: "parent" in relationships.groups
                and any(row.target_name == "beta"
                        for row in relationships.groups["parent"].rows.values()))
    parent_row = next(row for row in relationships.groups["parent"].rows.values()
                      if row.target_name == "beta")
    parent_row.scroll_visible(animate=False, immediate=True)
    await pilot.pause()
    assert await pilot.click(parent_row), "Right-sidebar Parent row was not physically clickable"
    await until(pilot, lambda: app.selected_session is first)
    await until(pilot, lambda: "NATIVE_RESPONSE_2" in conversation_paint(app.screen))
    assert await click_thread(app, pilot, "journey-child", "#any") is child_view
    await until(pilot, lambda: f"NATIVE_RESPONSE_{before + 1}" in conversation_paint(app.screen))
    assert len(requests) == before + 1 and parent_path.read_bytes() == original
    print("RIGHT_PARENT_ROW_AND_CHANNEL_CHILD_ROW_PHYSICAL_NAVIGATION_NO_REPLAY", flush=True)
    await click_tab(app, pilot, first.id)


async def channel_reply_feedback(app, pilot, comms, channel, first, entered=None, release=None,
                                 hold_next=None, requests=None, gamma=None, *,
                                 recipient_name="gamma",
                                 body="@gamma JOURNEY_CHANNEL_QUESTION"):
    assert gamma is not None
    from manual_live_turn_status import require_current_activity
    await click_tab(app, pilot, channel.id)
    chat = channel.query_one(CommsChatView)
    before = len(requests) if requests is not None else None
    if entered is not None:
        entered.clear()
        release.clear()
        hold_next.set()
    await submit_editor(pilot, chat.prompt.prompt_text_area, body)
    if entered is not None:
        await until(pilot, entered.is_set)
    await until(pilot, lambda: any(message.body == body
                                  for message, _ in chat.message_history.rows))
    originals = [message for message, _ in chat.message_history.rows
                 if message.body == body]
    assert len(originals) == 1
    original = originals[0]
    participants = chat.query_one(ChannelParticipants)
    await until(pilot, lambda: recipient_name in participants.names.render().plain)
    assert comms.registry.require(recipient_name).executing
    await click_tab(app, pilot, gamma.id)
    await until(pilot, lambda: gamma.conversation.agent.current_turn.busy)
    require_current_activity(gamma)
    await click_tab(app, pilot, channel.id)
    await until(pilot, lambda: "Responding" in str(message_feedback(chat, original).title))
    assert "Responding" in screen_paint(app)
    print("CHANNEL_NOTIFICATION_ACTUAL_NATIVE_WORKING_STATUS", flush=True)
    await click_tab(app, pilot, gamma.id)
    if release is not None:
        release.set()
    await until(pilot, lambda: not gamma.conversation.agent.current_turn.busy)
    require_current_activity(gamma)
    assert not comms.registry.require(recipient_name).executing
    assert app.selected_session is gamma
    print("CHANNEL_ORIGINAL_SETTLED_WHILE_HIDDEN", original.reference, flush=True)
    await click_tab(app, pilot, channel.id)
    if requests is not None:
        await until(pilot, lambda: f"NATIVE_RESPONSE_{before + 1}" in screen_paint(app))
    else:
        await until(pilot, lambda: any(
            message.sender == recipient_name and message.target == chat.target
            and message.seq > original.seq
            for message, _ in chat.message_history.rows))
        from agent_comms.input_disposition import InputDispositions
        from agent_comms.input_origin import WireInputOrigin
        recipient = comms.registry.require(recipient_name)
        native_input = InputDispositions(comms.root / InputDispositions.filename).read().lookup(
            InputDispositions.bus_key(original, recipient))
        assert native_input.has_started and native_input.matches_owner(recipient.incarnation)
        assert isinstance(native_input.origin, WireInputOrigin)
        assert native_input.origin.reference == original.reference
    await until(pilot, lambda: "Responded" in str(message_feedback(chat, original).title))
    outcomes = await asyncio.to_thread(comms.views.message_notifications, (original,))
    assert any(item.recipient == recipient_name and item.state == "Responded"
               for item in outcomes[original.seq, original.message_id])
    feedback = message_feedback(chat, original)
    title = feedback.query_one("CollapsibleTitle")
    title.scroll_visible(animate=False, immediate=True)
    await pilot.pause()
    assert await pilot.click(title), "Notification disclosure was not physically clickable"
    await until(pilot, lambda: f"{recipient_name}: Responded" in screen_paint(app))
    print("CHANNEL_RESPONDED_NOTIFICATION_DISCLOSURE_ACTUAL_PAINT", flush=True)
    if requests is not None:
        await until(pilot, lambda: len(requests) == before + 2)
        await until(pilot, lambda: comms.registry.require("beta").executing is False)
        await until(pilot, lambda: comms.registry.require(recipient_name).executing is False)
        assert "JOURNEY_CHANNEL_QUESTION" in str(requests[before]["messages"])
        assert f"NATIVE_RESPONSE_{before + 1}" in str(requests[-1]["messages"])
        await click_tab(app, pilot, first.id)
        await click_tab(app, pilot, channel.id)
        await until(pilot, lambda: f"NATIVE_RESPONSE_{before + 1}" in screen_paint(app))
        await pilot.pause(1.2)
        assert len(requests) == before + 2, "Reply caused replay or unbounded ping-pong"
    print("CHANNEL_REPLY_SAVED_HISTORY_AUTOMATIC_AUTHOR_NATIVE_OBSERVATION_NO_REPLAY"
          if requests is not None else "CHANNEL_ORIGINAL_REPLY_HANDLING_HIDDEN_RETURN",
          original.reference, flush=True)


async def configured_acceptance(app, pilot, agent, comms, receipt, subscriber):
    """The same native UI consumers with canonical configured input witnesses."""
    from agent_comms.input_disposition import InputDispositions
    from agent_comms.transcript_events import AssistantTranscript, UserTranscript
    from manual_live_turn_status import require_current_activity
    from toad.widgets.prompt import QueueSummary

    inputs = InputDispositions(comms.root / InputDispositions.filename)
    first = app.selected_session
    await first.wait_content_ready()
    view = first.conversation
    await until(pilot, lambda: view.agent_ready)
    await until(pilot, lambda: (
        view.transcript.displayed_cursor is not None
        and bool(view.window.histories)
        and all(history.state.reports_coverage for history in view.window.histories)
    ))
    await settled(pilot, view)
    assert ReaderCheckpoint.native_render_resources(first, app)
    assert inputs.read().rows == {}, "Attachment or history read sent a native input"
    receipt['completed_phases'].append('configured_saved_source_actual_paint')
    await independent_source_publication(view.agent, comms)

    sidebar = await wait_channel_roster(app, pilot, '#source529')
    row = next(row for row in sidebar.query(CommsRow) if row.target_name == '#source529')
    row.scroll_visible(animate=False, immediate=True)
    await pilot.pause()
    assert await pilot.click(row)
    await until(pilot, lambda: isinstance(app.selected_session, CommsScreen))
    channel = app.selected_session
    await channel.wait_content_ready()
    await until(pilot, lambda: 'CONFIGURED_SAVED_CHANNEL' in screen_paint(app))
    await click_tab(app, pilot, first.id)
    assert inputs.read().rows == {}
    receipt['completed_phases'].append('saved_channel_physical_open_return_no_input')

    # This peer is genuinely admitted by the original producer but has no saved
    # source yet. Its initial blank view receives no loaded-history credit.
    peer = await click_thread(app, pilot, 'peer529', '#source529')
    peer_text = 'New isolated acceptance input. Do not resume inherited work or use tools. Reply exactly CONFIGURED_PEER_FIRST.'
    await submit_editor(pilot, peer.conversation.prompt.prompt_text_area, peer_text)
    await until(pilot, lambda: comms.registry.require('peer529').executing
                and peer.conversation.agent.current_turn.busy)
    require_current_activity(peer)
    await click_tab(app, pilot, channel.id)
    participants = channel.query_one(ChannelParticipants)
    await click_participant(app, pilot, participants, 'peer529')
    await until(pilot, lambda: app.selected_session is peer)
    await until(pilot, lambda: not comms.registry.require('peer529').executing)
    await until(pilot, lambda: response_painted(app, peer.conversation, 'CONFIGURED_PEER_FIRST'))
    peer_originals = [row for row in inputs.read().rows.values()
                      if row.matches_owner(comms.registry.require('peer529').incarnation)
                      and row.source_text == peer_text]
    assert len(peer_originals) == 1 and peer_originals[0].has_started
    subscriber.require_success()
    receipt['completed_phases'].append('unopened_peer_first_input_participant_return')

    await click_tab(app, pilot, first.id)
    primary = 'New isolated acceptance input. Do not resume inherited work or use tools. Reply exactly CONFIGURED_FIRST_REPLY.'
    queued_text = 'Distinct isolated acceptance input. No tools. Reply exactly CONFIGURED_QUEUED_REPLY.'
    await submit_editor(pilot, view.prompt.prompt_text_area, primary)
    await until(pilot, lambda: view.agent.current_turn.busy)
    require_current_activity(first)
    await submit_editor(pilot, view.prompt.prompt_text_area, queued_text)
    await until(pilot, lambda: bool(view.queue_projection.items))
    queued = tuple(view.queue_projection.items)
    assert len(queued) == 1 and queued[0].text == queued_text
    assert queued_text in view.query_one(QueueSummary).render().plain
    await click_tab(app, pilot, channel.id)
    await click_tab(app, pilot, first.id)
    assert view.queue_projection.items and view.queue_projection.items[0].input_id == queued[0].input_id
    await until(pilot, lambda: not comms.registry.require('source529').executing
                and view.agent.presentation.prompt_in_flight == 0
                and not view.queue_projection.items)
    await pilot.press('end')
    await until(pilot, lambda: response_painted(app, view, 'CONFIGURED_QUEUED_REPLY'))
    started_queue = inputs.read().lookup('acp:' + queued[0].input_id)
    assert started_queue.has_started and started_queue.source_text == queued_text
    assert started_queue.matches_owner(comms.registry.require('source529').incarnation)
    subscriber.require_success()
    receipt['completed_phases'].append('configured_first_reply_busy_queue_status_history')

    # Fork through the original CLI dialog, then physically attach before its
    # actual first answer. No controlled provider gate is borrowed here.
    parent = Path(comms.registry.require('source529').session_file)
    parent_sha = hashlib.sha256(parent.read_bytes()).hexdigest()
    fork_text = 'New isolated acceptance input. Do not resume inherited work or use tools. Reply exactly CONFIGURED_FORK_FIRST.'
    await prepare_fork_dialog(app, pilot, comms, 'source529', '#source529',
                              'configured-child', fork_text, 'source529')
    await pilot.press('enter')
    await until(pilot, lambda: 'configured-child' in comms.registry.all_threads())
    child = await click_thread(app, pilot, 'configured-child', '#source529')
    await until(pilot, lambda: comms.registry.require('configured-child').executing)
    child_owner = comms.registry.require('configured-child')
    child_inputs = [row for row in inputs.read().rows.values()
                    if row.matches_owner(child_owner.incarnation) and row.source_text == fork_text]
    assert len(child_inputs) == 1 and child_inputs[0].has_started
    page = await child.conversation.agent.get_transcript_page()
    positions = [index for index, event in enumerate(page.events)
                 if isinstance(event, UserTranscript)
                 and event.native_id == child_inputs[0].native_id]
    assert len(positions) == 1
    assert not any(isinstance(event, AssistantTranscript)
                   for event in page.events[positions[0] + 1:])
    assert not response_painted(app, child.conversation, 'CONFIGURED_FORK_FIRST')
    assert hashlib.sha256(parent.read_bytes()).hexdigest() == parent_sha
    receipt['completed_phases'].append('native_fork_immediate_attachment_before_first_answer')
    await until(pilot, lambda: not comms.registry.require('configured-child').executing)
    await pilot.press('end')
    await until(pilot, lambda: response_painted(app, child.conversation, 'CONFIGURED_FORK_FIRST'))
    child_owner = comms.registry.require('configured-child')
    child_inputs = [row for row in inputs.read().rows.values()
                    if row.matches_owner(child_owner.incarnation) and row.source_text == fork_text]
    assert len(child_inputs) == 1 and child_inputs[0].has_started
    assert Path(child_owner.session_file).stat().st_size >= 40_000_000
    assert hashlib.sha256(parent.read_bytes()).hexdigest() == parent_sha
    subscriber.require_success()
    receipt['completed_phases'].append('fork_first_native_answer_parent_unchanged')

    # A and the real SDK/CLI fork both have genuinely loaded large sources.
    # The initially blank peer is deliberately excluded from this warm check.
    await clicked_reader_editor_return(app, pilot, first)
    await adaptive_reader_journey(app, pilot, None, tail_text='CONFIGURED_QUEUED_REPLY',
                                  input_count=lambda: len(inputs.read().rows))
    receipt['completed_phases'].append('large_saved_ABA_exact_warm_reader_draft_undo_reverse_End')
    await channel_reply_feedback(app, pilot, comms, channel, first, gamma=peer,
        recipient_name='peer529', body='@peer529 New isolated acceptance question. No tools. Reply exactly CONFIGURED_CHANNEL_REPLY.')
    subscriber.require_success()
    receipt['completed_phases'].append('configured_channel_reference_reply_handling_hidden_return')
    await direct_reply_feedback(pilot, app, comms, first.id, app.project_dir,
        target_name='source529', response_prefix=None,
        body='New isolated acceptance DM. No tools. Reply exactly CONFIGURED_DM_REPLY.')
    subscriber.require_success()
    receipt['completed_phases'].append('configured_DM_reference_reply_handling_hidden_cold_reopen')
    assert not any(row.unresolved for row in inputs.read().rows.values())
    from agent_comms.field_codec import FieldCodec
    receipt['native_inputs'] = FieldCodec.encode(inputs.read())


async def configured_main(*, core_source, core_artifacts=(), headless=True):
    """Borrow the original Core producer and its joined native runtime lifetime."""
    from compaction_source_successor_installed_journey import configured_saved_agent
    from original_owner_capture import CurrentTypedCapture
    from toad.agent_schema import AgentDefinition

    assert os.environ['AC_REAL_PROVIDER_AUTHORIZED'] == 'Sol/high retained acceptance'
    stage = Path(os.environ['AC_REAL_FIXTURE_STAGE'])
    evidence = Path(os.environ['L0A_EVIDENCE'])
    evidence.mkdir(mode=0o700, parents=True, exist_ok=False)
    capture = CurrentTypedCapture(Path(os.environ['AC_REAL_SOURCE_ROOT']),
                                 Path(os.environ['AC_REAL_ORIGINAL_PYTHON'])).read(
                                     os.environ['AC_REAL_SOURCE_OWNER'])
    original = Path(capture.source.session_file)
    assert original.stat().st_size >= 40_000_000
    original_sha = hashlib.sha256(original.read_bytes()).hexdigest()
    package = Path(os.environ['AC_NATIVE_COPIED_PACKAGE'])
    project = stage / 'project'
    subscriber = SavedStateSubscriber()
    receipt = {'complete': False, 'completed_phases': [], 'public_inputs': 0,
               'original_inputs_replayed': 0, 'source_file': str(original),
               'original_source_sha256': original_sha,
               'scope': 'configured continuous saved-source App/ACP/native journey; no loaded-cohort or performance qualification'}

    def current_source():
        capture.require_current()
        return capture.source, capture.retained

    def private_application(environment):
        # Keep the captured provider/model/auth and original native launch. Only
        # the private application directories and attempt witness are selected.
        environment.update(XDG_CONFIG_HOME=str(stage / 'config'),
            XDG_STATE_HOME=str(stage / 'state'), XDG_DATA_HOME=str(stage / 'data'),
            TOAD_TEST_ATTEMPT=stage.name, L0A_EVIDENCE=str(evidence),
            AGENT_COMMS_ACP_LAUNCHER=str(Path(sys.executable).with_name('agent-comms-acp')),
            AGENT_COMMS_AGENT_ARGS=shlex.join(capture.retained.arguments or ()))

    async with configured_saved_agent(stage, package, original, subscriber, receipt,
            core_source=core_source, core_artifacts=core_artifacts,
            capture_source=current_source, observe_launch=private_application,
            worktree=project, auto_wake=True) as (agent, owner, fork):
        service = agent._comms
        from agent_comms.field_codec import FieldCodec
        receipt['private_fork'] = FieldCodec.encode(fork)
        receipt['private_root'] = str(service.root)
        receipt['private_worktree'] = owner.worktree
        capture.require_current()
        assert hashlib.sha256(original.read_bytes()).hexdigest() == original_sha
        receipt['original_process_witness_released'] = True
        receipt['source_custody_unchanged_at_release'] = True
        print('PUBLIC_WITNESS_RELEASED', flush=True)
        # Canonical producer admission and bind_owned own these participants and
        # RuntimeServer. There is no copied registry or external server fixture.
        assert agent._runtime.server is not None
        service.messaging.send_message('peer529', '#source529',
                                       'CONFIGURED_SAVED_CHANNEL', notice=True)
        definition = AgentDefinition.decode({'name': 'Configured continuous native',
            'identity': 'configured-continuous', 'short_name': 'configured', 'protocol': 'acp',
            'run_command': {'*': shlex.join([sys.executable, '-m', 'agent_comms.acp'])}})
        app = InstalledApp(agent_data=definition, project_dir=str(project),
                           agent_session_id=owner.name)
        try:
            async with app.run_test(headless=headless, size=(160, 44)) as pilot:
                await configured_acceptance(app, pilot, agent, service, receipt, subscriber)
                assert app._exception is None
            assert app.preparation._closed
            receipt['app_complete'] = True
        except BaseException:
            (evidence / 'acceptance-failure.txt').write_text(traceback.format_exc())
            raise
    assert receipt['native_children_closed'] and receipt['original_source_unchanged']
    receipt['complete'] = True
    (evidence / 'configured-journey.json').write_text(json.dumps(receipt, indent=2) + '\n')


if __name__ == "__main__":
    import argparse
    from functools import partial

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--warm-only", action="store_true",
                        help="Stop after the original saved warm A/B/A and Undo checks")
    parser.add_argument("--configured-saved", action="store_true",
                        help="Acquire the original configured >=40MB source through Core's joined producer")
    parser.add_argument("--core-checkout", type=Path,
                        help="Exact reviewed Core fixture/cutover helper checkout, not a production overlay")
    parser.add_argument("--headful", action="store_true")
    args, remaining = parser.parse_known_args()
    if args.configured_saved:
        assert not args.warm_only and args.core_checkout is not None
        # Only original outside-package fixture helpers are added. Production
        # agent_comms/toad/textual continue to resolve from the issued prefix.
        sys.path[:0] = [str(args.core_checkout / 'tests'),
                       str(args.core_checkout / 'tools' / 'cutover')]
        from publish_retained_summary import InstalledSource
        core_source, archives, remaining = InstalledSource.command_arguments(remaining)
        assert not remaining, remaining
        asyncio.run(configured_main(core_source=core_source, core_artifacts=archives,
                                    headless=not args.headful))
    else:
        assert not remaining and args.core_checkout is None
        asyncio.run(native_fixture(
            app_type=StreamJourneyApp, prepare_state=prepare_saved_state,
            acceptance=partial(acceptance, warm_only=args.warm_only),
            provider_reply=streamed_reply, provider_chunk_characters=40,
            headless=not args.headful,
        ))
