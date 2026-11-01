"""External mailbox and channel sources share the real BUS submission lifecycle."""

import pytest
from textual.widgets import Button

from agent_comms.repo import Checkout
from agent_comms.thread_execution import ExternalThreadExecution
from agent_comms.threads import Thread
from support.workspace import Workspace
from toad.core.input_events import UserInputSubmitted
from toad.navigation_context import NavigationContext
from toad.navigation_target import ChannelTarget, NavigationTarget, ThreadTarget
from toad.screens.queue import QueueInspection


@pytest.mark.parametrize("target", (ChannelTarget("#team"), ThreadTarget("cli-peer")))
async def test_bus_sources_keep_publication_draft_and_queue_authority_separate(
    workspace: Workspace, target: NavigationTarget,
) -> None:
    comms = workspace.comms
    comms.registry.declare(Thread(
        "cli-peer", frozenset({"team"}), Checkout(workspace.project),
        execution=ExternalThreadExecution,
    ))
    comms.messaging.send("cli-peer", "#team", "READY_EXTERNAL_SOURCE")
    async with workspace.app(size=(115, 38)) as ui:
        app = ui.app
        owner_tab = ui.selected_tab
        context = NavigationContext(app, owner_tab, app.project_dir, workspace.viewer)
        source_tab = await target.open(context)
        await app.selected_session.wait_content_ready()
        view = ui.conversation
        await ui.until(lambda: "READY_EXTERNAL_SOURCE" in ui.painted(view.window),
                       why="the original assigned BUS source")
        await ui.write_draft("Keep this different unsent draft")
        editor = view.prompt.prompt_text_area
        document, undo = editor.document, editor.history
        before = comms.bus.bus.revision()
        body = f"ORIGINAL_BUS_SUBMISSION_{target.name}_{workspace.roots.attempt.name}"
        await view.submit_input(UserInputSubmitted(body))
        await ui.until(lambda: body in ui.painted(view.window) and not view.send_block_reason,
                       why="original publication acknowledged by its source")
        (sent,) = comms.bus.bus.latest_addressed(
            frozenset((workspace.viewer,)), frozenset((target.name,)))
        assert sent.body == body
        assert comms.bus.bus.revision() == before + 1
        assert view.contains_user_message(sent)
        assert not view.submissions.retains_surface
        assert view.prompt.text == "Keep this different unsent draft"
        assert editor.document is document and editor.history is undo
        assert not view.queue_source.queue_actions_available(view.agent_binding.presentation)
        view.open_queue_menu()
        await ui.until(lambda: isinstance(app.screen, QueueInspection), why="original queue inspection")
        inspection = app.screen
        await ui.until(
            lambda: bool(inspection.query("#queue-send-now")) and bool(inspection.query("#queue-clear")),
            why="the mounted queue action controls",
        )
        assert inspection.source_view is view
        assert inspection.query_one("#queue-send-now", Button).disabled
        assert inspection.query_one("#queue-clear", Button).disabled
        await ui.press("escape")
        await ui.until(lambda: app.screen is not inspection, why="queue inspection dismissed")
        histories = tuple(view.contents.line_histories())
        pages = tuple(page for history in histories for page in history.pages)
        assert histories and pages
        await ui.select_tab(owner_tab)
        await ui.select_tab(source_tab)
        assert ui.conversation is view
        assert tuple(view.contents.line_histories()) == histories
        assert tuple(page for history in histories for page in history.pages) == pages
        await ui.until(lambda: body in ui.painted(view.window), why="original source after tab return")
        assert view.prompt.text == "Keep this different unsent draft"
        assert editor.document is document and editor.history is undo
        assert comms.bus.bus.revision() == before + 1
        assert not workspace.child_processes("agent_comms.pi_native")
