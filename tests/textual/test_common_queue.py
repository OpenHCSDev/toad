"""Common queue chrome uses real source references and never grants BUS ACP actions.

These controls use the private wire, real observer, prompt and submission owner.
No product monkeypatches and no provider input are needed.
"""
import pytest
from agent_comms.acp_extension import NoQueueScope
from toad.session_presentation import MailboxSessionSources
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.prompt import QueueSummary
from textual.widgets import Button


async def open_channel(ui, viewer):
    return await ui.open_channel("#team", actor=viewer)


async def open_direct(ui, viewer):
    return await ui.open_direct("peer", actor=viewer)


@pytest.mark.parametrize("open_surface", [open_channel, open_direct])
async def test_bus_queue_borrows_original_proofs_and_preserves_draft(workspace, open_surface):
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
        assert view.query_one(QueueSummary) in ui.app.screen._compositor.visible_widgets
        assert not owner.queue_source.queue_actions_available(owner)
        with pytest.raises(ValueError):
            await owner.queue_source.queue_clear(owner, NoQueueScope())
        with pytest.raises(ValueError):
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


async def test_mailbox_factory_supplies_same_owner_and_readonly_capability_wins_mro(workspace):
    async with workspace.app(size=(110, 35)) as ui:
        view = ui.conversation
        source = MailboxSessionSources()
        prompt = source.prompt(view)
        assert prompt.operational_submissions is view.submissions
        assert not source.queue_actions_available(view.submissions)
        with pytest.raises(ValueError):
            await source.queue_send_now(view.submissions, source.queue_scope(view.submissions))
        with pytest.raises(ValueError):
            await source.queue_clear(view.submissions, source.queue_scope(view.submissions))
        await source.close()
