"""Regression test for pooled Textual `Prompt` rebinding with live `NeovimEditing`.

Switching tabs via `WorkspaceComposerPool` captures the outgoing tab's `TextAreaState`
(which moves `NeovimEditing._receiver` to `RetainedReceiver`). Rebinding the pooled
`Prompt` onto a fresh tab must attach a fresh `EditingMode` without touching the outgoing
tab's captured Neovim buffer, and returning to the first tab must re-attach its retained
`NeovimEditing` (`AttachedReceiver`) so vim motions, mode badges, and boundaries keep
working. Discarding a tab's draft must close its retained Neovim buffer.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from agent_comms.projects.checkouts import Checkout
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.screen import Screen

from toad.client.bus_submission import BusSubmissions, SubmissionView
from toad.client.composer_pool import ComposerPoolHost, WorkspaceComposerPool
from toad.client.input_attention import InputAttention
from toad.core.link_context_changed import CoreEventStream
from toad.key_modes import KeyMode, VimNormal
from toad.neovim_editing import HostsNeovim, NeovimEditing
from toad.project_path_owner import ProjectPathOwner
from toad.textual_colours import ThemedApp
from toad.widgets.prompt import MessagePrompt, Prompt


class _VimTab(ComposerPoolHost, SubmissionView, ProjectPathOwner, Vertical):
    """Minimal mounted host mirroring `DeliveryFailureView` + `CommsChatView` pooling."""

    composer_placeholder = "Message #comms"

    def __init__(self, *, id: str) -> None:
        super().__init__(id=id)
        self.core_publications = CoreEventStream(self)
        self.submissions = BusSubmissions(self)
        self.project_path = Checkout(Path.cwd())
        self.working_directory = Path.cwd()
        self.agent_info = None
        self.agent_binding = None
        self.model_history_scope = None
        self.status = ""

    @property
    def project_root(self) -> Path:
        return self.project_path.path

    @property
    def coordination_root(self) -> Path:
        return self.project_path.path

    @property
    def active_composer(self) -> Prompt | None:
        return self.query_one_optional(Prompt)

    def restore_composer_draft(self, text: str) -> None:
        pass

    def show_send_failure(self, text: str) -> None:
        pass

    def run_submission(self, send):
        return asyncio.create_task(send())

    def submissions_changed(self) -> None:
        pass

    def draws_user_message(self) -> bool:
        return True

    def record_input(self, text: str) -> None:
        pass

    def apply_compose_access(self, composer, access) -> None:
        pass

    @property
    def submission_composer(self):
        return self.active_composer

    def queue_controls_changed(self) -> None:
        pass


class _VimScreen(Screen):
    key_mode: type[KeyMode] = VimNormal

    def __init__(self) -> None:
        super().__init__()
        self.pool = WorkspaceComposerPool()

    def compose(self) -> ComposeResult:
        yield _VimTab(id="tab-a")
        yield _VimTab(id="tab-b")


class _TestAttention(InputAttention):
    def deliver(self, sequence: str) -> None:
        pass

    def publish_title(self, title: str) -> None:
        pass


class _PooledVimApp(HostsNeovim, ThemedApp[None]):
    def __init__(self) -> None:
        super().__init__()
        self.input_attention = _TestAttention(self)


async def _wait_neovim_ready(editor, *, timeout: float = 5.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        mode = editor.editing_mode
        if isinstance(mode, NeovimEditing) and mode.completed and mode._receiver.owns(editor):
            return
        await asyncio.sleep(0.02)
    raise AssertionError(
        f"Neovim did not settle: mode={editor.editing_mode!r}, "
        f"completed={getattr(editor.editing_mode, 'completed', None)}, "
        f"owns={getattr(getattr(editor.editing_mode, '_receiver', None), 'owns', lambda _: False)(editor)}"
    )


async def _wait_text(editor, expected: str, *, timeout: float = 5.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if editor.text == expected and editor.editing_mode.completed:
            return
        await asyncio.sleep(0.02)
    assert editor.text == expected


@pytest.mark.asyncio
async def test_pooled_prompt_rebind_preserves_live_neovim_across_tabs() -> None:
    app = _PooledVimApp()
    async with app.run_test(size=(100, 30)) as pilot:
        screen = _VimScreen()
        await app.push_screen(screen)
        await pilot.pause()
        tab_a = screen.query_one("#tab-a", _VimTab)
        tab_b = screen.query_one("#tab-b", _VimTab)

        prompt = MessagePrompt(project=tab_a.project_path, submissions=tab_a.submissions)
        await tab_a.mount(prompt)
        screen.pool.register(MessagePrompt, tab_a, prompt)
        editor = prompt.prompt_text_area
        editor.focus()
        await _wait_neovim_ready(editor)

        mode_a = editor.editing_mode
        assert isinstance(mode_a, VimNormal)
        assert mode_a._receiver.owns(editor)

        # Enter insert mode in tab A, type "alpha", return to normal mode.
        for key in ("i", "a", "l", "p", "h", "a", "escape"):
            await pilot.press(key)
        await _wait_text(editor, "alpha")
        assert mode_a.label == "NORMAL"

        # Switch to fresh tab B through the shared WorkspaceComposerPool.
        reused, was_reused = screen.pool.acquire(
            MessagePrompt, tab_b, lambda: MessagePrompt(project=tab_b.project_path, submissions=tab_b.submissions)
        )
        assert was_reused and reused is prompt
        prompt.reparent(tab_b)
        editor.focus()
        await _wait_neovim_ready(editor)

        mode_b = editor.editing_mode
        assert isinstance(mode_b, VimNormal)
        assert mode_b is not mode_a
        assert mode_b._receiver.owns(editor)
        assert not mode_a._receiver.owns(editor)
        assert editor.text == ""

        # Vim editing must work live in tab B without corrupting tab A's draft.
        for key in ("i", "b", "e", "t", "a", "escape", "x"):
            await pilot.press(key)
        await _wait_text(editor, "bet")
        assert mode_b.label == "NORMAL"
        assert screen.pool.saved_draft(tab_a).text == "alpha"

        # Switch back to tab A: its retained NeovimEditing buffer must re-attach live.
        reused_a, was_reused_a = screen.pool.acquire(
            MessagePrompt, tab_a, lambda: MessagePrompt(project=tab_a.project_path, submissions=tab_a.submissions)
        )
        assert was_reused_a and reused_a is prompt
        prompt.reparent(tab_a)
        editor.focus()
        await _wait_neovim_ready(editor)

        assert editor.editing_mode is mode_a
        assert mode_a._receiver.owns(editor)
        assert editor.text == "alpha"

        # Vim motions & insert must still work in tab A after re-attaching.
        for key in ("A", "!", "escape"):
            await pilot.press(key)
        await _wait_text(editor, "alpha!")
        assert mode_a.label == "NORMAL"

        # Discarding tab B's draft closes its retained Neovim buffer cleanly.
        screen.pool.release(tab_b, keep_draft=False)
        await asyncio.sleep(0.05)
        assert screen.pool.saved_draft(tab_b) is None
