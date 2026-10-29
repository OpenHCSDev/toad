"""Common queue chrome uses real source references and never grants BUS ACP actions.

These controls use the private wire, real observer, prompt and submission owner.
No product monkeypatches and no provider input are needed.
"""
from collections.abc import Awaitable, Callable

import pytest
from agent_comms.bus import Bus
from agent_comms.channel_targets import ThreadTarget
from agent_comms.read_basis import DisplayOutcomes
from agent_comms.presentation import MessageNotification
from agent_comms.recorded_bus import RecordedBusIdentity
from support.ui import Ui
from support.workspace import Workspace
from agent_comms.acp_extension import NoQueueScope
from toad.notification_status import CheckedNotifications, EmptyCheckedNotifications
from toad.submission_queue import QueueActionRefused
from toad.session_presentation import MailboxSessionSources
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.prompt import QueueSummary
from textual.widgets import Button


async def open_channel(ui: Ui, viewer: str) -> str:
    # The tab acts as an agent; the Core page is still read by the actual human.
    return await ui.open_channel("#team", actor="peer")


async def open_direct(ui: Ui, viewer: str) -> str:
    return await ui.open_direct("peer", actor=viewer)


@pytest.mark.parametrize("open_surface", [open_channel, open_direct])
async def test_bus_queue_borrows_original_proofs_and_preserves_draft(
    workspace: Workspace, open_surface: Callable[[Ui, str], Awaitable[str]],
) -> None:
    workspace.thread("peer", "team")
    workspace.thread("recipient", "team")
    originals = (
        workspace.comms.messaging.send("peer", "#team", "CHANNEL ORIGINAL").message,
        workspace.comms.messaging.send("peer", workspace.viewer, "DIRECT ORIGINAL").message,
    )
    async with workspace.app(size=(115, 38)) as ui:
        await open_surface(ui, workspace.viewer)
        view = ui.app.selected_session.query_one(CommsChatView)
        owner = view.submissions
        await ui.until(lambda: bool(owner.message_queue_entries), why="visible original-reference evidence")
        await ui.write_draft("@peer kept draft")
        entries = owner.message_queue_entries
        assert all(entry.reference in {message.reference for message in originals} for entry in entries)
        assert all(entry.request.root == str(workspace.comms.root) for entry in entries)
        captured = {page.prepared.notification_identity for page in view.message_history.pages}
        human = workspace.comms.registry.require(workspace.viewer).incarnation
        assert all(entry.request.display in captured for entry in entries)
        namespace = RecordedBusIdentity.capture(Bus.path_in(workspace.comms.root))
        assert all(entry.request.display.outcome_viewer() == DisplayOutcomes(human, namespace)
                   for entry in entries)
        assert not view.message_history.undrawn
        assert view.query_one(QueueSummary) in ui.app.screen._compositor.visible_widgets
        assert not owner.queue_source.queue_actions_available(owner)
        with pytest.raises(QueueActionRefused):
            await owner.queue_source.queue_clear(owner, NoQueueScope())
        with pytest.raises(QueueActionRefused):
            await owner.queue_source.queue_send_now(owner, NoQueueScope())

        previous_screen = ui.app.screen
        screen = owner.inspect_queue()
        await ui.until(lambda: ui.app.screen is screen, why="shared queue inspection")
        assert screen.query_one("#queue-send-now", Button).disabled
        assert screen.query_one("#queue-clear", Button).disabled
        await ui.textual[1].click("#queue-close")
        await ui.until(lambda: ui.app.screen is previous_screen, why="queue inspection closed")
        assert ui.draft() == "@peer kept draft"

        workspace.comms.messaging.send("peer", "#team", "LATER CHANNEL ORIGINAL")
        workspace.comms.messaging.send("peer", workspace.viewer, "LATER DIRECT ORIGINAL")
        previous = {entry.reference for entry in entries}
        await ui.until(lambda: bool({entry.reference for entry in owner.message_queue_entries} - previous),
                       why="source subscription to refresh the existing queue consumer")
        captured = {page.prepared.notification_identity for page in view.message_history.pages}
        assert all(entry.request.display in captured for entry in owner.message_queue_entries)
        assert ui.draft() == "@peer kept draft"


async def test_mailbox_factory_supplies_same_owner_and_readonly_capability_wins_mro(workspace: Workspace) -> None:
    async with workspace.app(size=(110, 35)) as ui:
        view = ui.conversation
        source = MailboxSessionSources()
        prompt = source.prompt(view)
        assert prompt.operational_submissions is view.submissions
        assert not source.queue_actions_available(view.submissions)
        with pytest.raises(QueueActionRefused):
            await source.queue_send_now(view.submissions, source.queue_scope(view.submissions))
        with pytest.raises(QueueActionRefused):
            await source.queue_clear(view.submissions, source.queue_scope(view.submissions))
        await source.close()


def test_matched_empty_feedback_is_not_a_missing_original(workspace: Workspace) -> None:
    workspace.thread('peer', 'team')
    comms = workspace.comms
    human = comms.registry.require(workspace.viewer)
    first = comms.messaging.send('peer', human.name, 'matched original').message
    missing = comms.messaging.send('peer', human.name, 'not in this result window').message
    page = comms.views.dm_display_page(ThreadTarget('peer'), worktree=human.worktree)
    comms.views.mark_page_read(page, worktree=human.worktree)
    document = comms.bus.reads.read()
    window = comms.views.message_notifications_for_references(
        page.selection.notification_identity.outcome_viewer(), (first.reference,),
    )
    checked, = CheckedNotifications.for_references((first.reference,), window.outcomes)
    assert isinstance(checked, EmptyCheckedNotifications)
    assert checked.notifications == ()
    assert checked.queue_title == "No recipient feedback"
    assert not checked.unavailable and not checked.working
    assert checked.title == MessageNotification.summary(checked.notifications)
    assert tuple(CheckedNotifications.for_references((missing.reference,), window.outcomes)) == ()
    assert comms.bus.reads.read() == document
