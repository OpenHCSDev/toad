"""Two physical Pi saved histories -> installed typed thread target -> user UI.

One continuous native/ACP/normalApp path, no Agent/reader/render/transport mocks.
Model responses are controlled on localhost. All wire/project/config are private.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from weakref import ref

from acp.schema import TextContentBlock
from agent_comms.acp import CommsClient
from agent_comms.threads import Thread
from l0a_native_installed_pilot import main as native_fixture, until
from native_session_retention_pilot import InstalledApp, conversation_paint
from saved_state_user_journey_pilot import SavedStateSubscriber, click_tab
from toad.navigation_preparation import NativeThreadNavigation, ThreadNavigationRequest, StoppedThreadNavigation
from toad.navigation_target import ThreadTarget
from toad.thread_navigation import ThreadOrigin
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.agent_response import AgentResponse
from toad.session_admission import SessionAdmission
from toad.session_tracker import OpenTab
from toad.screens.file_preview import FilePreviewScreen


def reply(request, number):
    return ({"role": "assistant", "content": f"SAVED_NAVIGATION_NATIVE_REPLY_{number}"}, "stop")


async def prepare(comms, project, requests, entered, release, hold_next):
    release.set()
    comms.registry.declare(Thread("alpha", frozenset({"team"}), str(project),
                                 model="selected-offline/fixture", thinking_level="off"))
    comms.registry.declare(Thread("stopped", frozenset({"team"}), str(project),
                                 model="selected-offline/fixture", thinking_level="off"))
    # A declaration without a PID is still an admitted active launch. Retire
    # its actual registration to exercise a genuinely stopped history route.
    comms.registry.unregister("stopped")
    (project / "admission-note.txt").write_text("DECLARED_ADMISSION_ACTUAL_FILE_PAINT\n")
    client = CommsClient(comms, runtime_enabled=True,
        private_nk_native_package=Path(os.environ["AC_NATIVE_COPIED_PACKAGE"]),
        private_nk_wire_root_id=os.environ["AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID"])
    observer = SavedStateSubscriber()
    client.on_connect(observer)
    try:
        for name in ("alpha", "beta"):
            await client.load_session(cwd=str(project), session_id=name)
            async with asyncio.timeout(20):
                await client.prompt(name, [TextContentBlock(type="text", text=f"SAVED_NAVIGATION_INPUT_{name}")])
            observer.require_success()
        assert len(requests) == 2
    finally:
        await client.shutdown()


async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    source = app.selected_session
    view = source.conversation
    beta_mode = app.selected_mode
    await until(pilot, lambda: "SAVED_NAVIGATION_NATIVE_REPLY_2" in conversation_paint(app.screen))
    editor = view.prompt.prompt_text_area
    editor.insert("NAVIGATION_DRAFT_STAYS")
    editor.history.checkpoint()
    editor.insert(" and undo")
    document, undo, draft = editor.document, editor.history, editor.text
    native_files = {name: Path(comms.registry.require(name).session_file) for name in ("alpha", "beta")}
    native_bytes = {name: path.read_bytes() for name, path in native_files.items()}
    before_tabs = tuple(app.tab_order.names)
    origin = ThreadOrigin.capture(app, source)
    assert origin.current(app.thread_navigation, beta_mode)
    context = source.navigation_context

    # Actual asyncio request admission happens before its off-loop metadata read.
    # One UI waiter cancels while its sibling still owns the same intent.
    primary = asyncio.create_task(ThreadTarget("alpha").open(context))
    duplicate = asyncio.create_task(ThreadTarget("alpha").open(context))
    await asyncio.sleep(0)
    assert len(app.thread_navigation.pending) == 1
    opening, = app.thread_navigation.pending.values()
    primary.cancel()
    outcome, = await asyncio.gather(primary, return_exceptions=True)
    assert isinstance(outcome, asyncio.CancelledError)
    assert not opening.task.cancelled()
    alpha_mode = await asyncio.wait_for(duplicate, 20)
    assert app.selected_mode == alpha_mode and alpha_mode not in before_tabs
    await until(pilot, lambda: "SAVED_NAVIGATION_NATIVE_REPLY_1" in conversation_paint(app.screen))
    assert len(app.tab_order.names) == len(before_tabs) + 1
    assert not app.thread_navigation.pending
    assert not origin.current(app.thread_navigation, beta_mode)
    alpha = app.selected_session
    assert alpha._comms_thread == "alpha" and alpha.coordination_root == str(comms.root)
    alpha_editor = alpha.conversation.prompt.prompt_text_area
    alpha_editor.insert("ALPHA_UNSENT_DRAFT")
    alpha_document, alpha_undo = alpha_editor.document, alpha_editor.history
    alpha_bodies = tuple(ref(body) for body in alpha.conversation.query(AgentResponse)
                         if body in app.screen._compositor.visible_widgets
                         and body.region.overlaps(alpha.conversation.window.scrollable_content_region))
    assert alpha_bodies, "Loaded Alpha must have an actually painted native response"
    print("PASS_ACTUAL_NATIVE_OPEN_DUPLICATE_CANCELLED_WAITER_ONE_TAB_PAINT", flush=True)

    # The existing mounted route focuses the original logical source/body;
    # no provisional tab or extra Native prompt is permitted.
    reused = await ThreadTarget("alpha").open(alpha.navigation_context)
    assert reused == alpha_mode and len(app.tab_order.names) == len(before_tabs) + 1
    await click_tab(app, pilot, beta_mode)
    await until(pilot, lambda: "SAVED_NAVIGATION_NATIVE_REPLY_2" in conversation_paint(app.screen))
    beta = app.selected_session.conversation
    assert beta.prompt.prompt_text_area.document is document
    assert beta.prompt.prompt_text_area.history is undo and beta.prompt.prompt_text_area.text == draft
    assert origin.current(app.thread_navigation, beta_mode)

    stopped = ThreadNavigationRequest(str(comms.root), "stopped", view.project_path, ()).read()
    assert isinstance(stopped, StoppedThreadNavigation) and not stopped.attachable
    stopped_mode = await ThreadTarget("stopped").open(app.selected_session.navigation_context)
    chat = app.selected_session.query_one(CommsChatView)
    assert chat.target == "stopped" and chat.kind == "dm"
    await until(pilot, lambda: "stopped" in "\n".join(
        strip.text for strip in app.screen._compositor.render_strips()))
    assert not app.thread_navigation.pending
    assert not comms.registry.status("stopped").active
    await click_tab(app, pilot, alpha_mode)
    await until(pilot, lambda: "SAVED_NAVIGATION_NATIVE_REPLY_1" in conversation_paint(app.screen))
    returned = app.selected_session.conversation.prompt.prompt_text_area
    assert returned.document is alpha_document and returned.history is alpha_undo
    assert returned.text == "ALPHA_UNSENT_DRAFT"
    retained_alpha = sum(body() in app.screen._compositor.visible_widgets for body in alpha_bodies)
    print("ACTUAL_WARM_RETURN_ORIGINAL_NATIVE_BODIES", retained_alpha, len(alpha_bodies), flush=True)

    # A genuinely new admitted case needs one declaration, not edits to the
    # App's open/tab/return/close switches or another membership map.
    note = view.project_path / "admission-note.txt"
    class ReviewNoteAdmission(SessionAdmission):
        def __call__(self):
            return FilePreviewScreen(note)

        @property
        def address(self):
            return note

        def tab(self, sessions, snapshot):
            return OpenTab(self.mode, "Admission note")

    review = ReviewNoteAdmission("review-note")
    await app.session_navigation.admit(review, after=alpha_mode)
    await until(pilot, lambda: "DECLARED_ADMISSION_ACTUAL_FILE_PAINT" in "\n".join(
        strip.text for strip in app.screen._compositor.render_strips()))
    assert app.workspace_sessions.factories[review.mode] is review
    assert app.session_navigation.find(note) is review
    await app.session_navigation.close(review.mode)
    assert review.mode not in app.workspace_sessions.factories
    assert review.mode not in app.workspace_sessions.views
    assert app.selected_mode == alpha_mode
    await until(pilot, lambda: "SAVED_NAVIGATION_NATIVE_REPLY_1" in conversation_paint(app.screen))

    # The production preview case shares admission and close, retains its
    # exact origin, and reuses the one already admitted file.
    preview = await app.session_navigation.preview(note)
    await until(pilot, lambda: "DECLARED_ADMISSION_ACTUAL_FILE_PAINT" in "\n".join(
        strip.text for strip in app.screen._compositor.render_strips()))
    assert await app.session_navigation.preview(note) == preview
    await app.session_navigation.close(preview)
    assert app.selected_mode == alpha_mode and preview not in app.workspace_sessions.factories
    print("PASS_NEW_CASE_SINGLE_DECLARATION_REAL_FILE_PROJECTION_RETURN_CLOSE_PREVIEW_REUSE", flush=True)
    assert retained_alpha == len(alpha_bodies), "Returning the native tab discarded its original painted bodies"
    await pilot.resize_terminal(112, 34)
    await pilot.pause()
    assert len(requests) == 2
    assert all(path.read_bytes() == native_bytes[name] for name, path in native_files.items())
    assert app._exception is None
    Path(os.environ["L0A_EVIDENCE"], "journey.json").write_text(json.dumps({
        "pass": True, "source_head": os.environ.get("TOAD_TEST_SOURCE_HEAD"),
        "physical_saved_native_inputs": len(requests), "one_tab_for_duplicate": True,
        "cancelled_waiter_surviving_owned_task": True, "native_reuse": alpha_mode,
        "stopped_direct_route_no_start": stopped_mode,
        "original_editor_documents_undo_drafts": True, "native_journals_unchanged": True,
        "original_native_warm_bodies": [retained_alpha, len(alpha_bodies)],
        "new_case_one_declaration_actual_file_paint_close": True,
        "preview_reuse_close_origin": True,
    }, indent=2) + "\n")
    print("PASS_SAVED_NATIVE_REUSE_STOPPED_DM_TAB_RETURN_RESIZE_DRAFT_NO_REPLAY", flush=True)


if __name__ == "__main__":
    asyncio.run(native_fixture(app_type=InstalledApp, prepare_state=prepare,
                              provider_reply=reply, acceptance=acceptance))
