"""Comms chat view: a full main-pane view for one channel or DM.

IRC semantics inside Toad: clicking a channel or thread in the sidebar
replaces the agent conversation pane with this view — the target's
history plus an input that sends directly on the wire. Selecting the
session thread returns to the agent conversation.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Input, Static

from agent_comms.operations import wire


def _comms_root() -> Path:
    return Path(os.environ.get("AGENT_COMMS_ROOT", "~/.agent-comms")).expanduser()


def session_thread_name(project_path) -> str:
    """The wire thread name for a Toad project directory (ACP naming)."""
    import re

    return re.sub(r"[^A-Za-z0-9_-]+", "-", Path(project_path).name or "session").strip("-") or "session"


def switch_comms_target(screen, event) -> None:
    """IRC view switching: swap the conversation pane for a chat view.

    A thin, self-contained function so MainScreen's handler cannot crash
    the app: every failure is contained to the chat view's error line.
    """
    from toad.widgets.conversation import Conversation

    try:
        conversation = screen.query_one(Conversation)
        chat = screen.query_one("#comms-chat", CommsChatView)
    except Exception:
        return
    try:
        session_name = session_thread_name(screen.project_path)
    except Exception:
        session_name = ""
    if event.kind == "session" or (
        event.target == session_name and session_name != ""
    ):
        # The session thread always returns to the agent conversation,
        # whichever kind the sidebar assigned it.
        conversation.display = True
        chat.display = False
        return
    try:
        chat.open_target(event.target, event.kind, me=session_name)
        conversation.display = False
        chat.display = True
        from textual.widgets import Input

        chat.query_one("#chat-input", Input).focus()
    except Exception as error:
        chat.display = True
        chat.query_one("#chat-body", Static).update(f"view error: {error}")


class CommsChatView(Vertical):
    """History + composer for one target (channel or DM peer)."""

    DEFAULT_CSS = """
    CommsChatView { height: 1fr; }
    CommsChatView #chat-header {
        height: 1;
        padding: 0 1;
        background: $surface;
        color: $text-muted;
    }
    CommsChatView #chat-history {
        height: 1fr;
        padding: 0 1;
    }
    CommsChatView Input { border: none; height: 3; }
    """

    target: reactive[str] = reactive("", init=False)
    kind: reactive[str] = reactive("channel", init=False)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._me: str | None = None

    def compose(self) -> ComposeResult:
        yield Static("", id="chat-header")
        yield VerticalScroll(Static("", id="chat-body"), id="chat-history")
        yield Input(placeholder="", id="chat-input")

    def on_mount(self) -> None:
        self.set_interval(1.0, self._refresh)
        self._refresh()

    BINDINGS = [("escape", "back_to_session", "Back to session")]

    def open_target(self, target: str, kind: str, me: str | None = None) -> None:
        """Switch this view to a target: channel, DM peer, or the IRC feed.

        ``me`` is the session thread name (DMs are logged against it).
        """
        self.target = target
        self.kind = kind
        self._me = me
        header = self.query_one("#chat-header", Static)
        if kind == "irc":
            label = "→ IRC (everything on the wire; sends to #all)"
            placeholder = "message the room (#all)…"
        else:
            label = f"→ {target}" + (" (DM)" if kind == "dm" else "")
            placeholder = f"message {target}…"
        header.update(label)
        input_field = self.query_one("#chat-input", Input)
        input_field.placeholder = placeholder
        self._refresh()

    def action_back_to_session(self) -> None:
        from toad.widgets.comms_sidebar import SelectTarget

        me = self._me or ""
        self.post_message(SelectTarget(me, "session"))

    def _refresh(self) -> None:
        if not self.target:
            return
        comms = wire(_comms_root())
        body = self.query_one("#chat-body", Static)
        now = time.time()
        lines: list[str] = []
        try:
            if self.kind == "irc":
                messages = list(comms.full_history())
            elif self.kind == "dm" and self._me:
                messages = list(comms.dm_history(self._me, self.target))
            else:
                messages = list(comms.channel_history(self.target))
        except Exception as error:
            body.update(f"error: {error}")
            return
        for message in messages:
            ts = time.strftime("%H:%M", time.localtime(message.timestamp))
            age = int(now - message.timestamp)
            stamp = ts if age < 86400 else f"{int(age // 86400)}d"
            body_text = message.body.replace("\n", " ⏎ ")
            lines.append(f"[{stamp}] {message.sender} → {message.target}: {body_text}")
        if not lines:
            lines.append("(no messages yet — say hi)")
        body.update("\n".join(lines[-200:]))
        scroll = self.query_one("#chat-history", VerticalScroll)
        scroll.scroll_end(animate=False)
        # Viewing counts as reading for DMs to the session thread.
        if self.kind == "dm" and self._me == self.target:
            comms.acknowledge(self._me)

    @on(Input.Submitted)
    def _send(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        input_field = self.query_one("#chat-input", Input)
        input_field.value = ""
        if not text or not self.target:
            return
        sender = self._me or "human"
        try:
            comms = wire(_comms_root())
            if sender not in comms.registry:
                from agent_comms import Thread

                comms.register(
                    Thread(
                        name=sender,
                        tags=frozenset({"human"}),
                        worktree=str(Path.cwd()),
                    )
                )
            if self.kind == "dm":
                comms.send(sender, self.target, text)
            else:
                comms.send(sender, self.target, text)
        except Exception as error:
            self.query_one("#chat-body", Static).update(f"send failed: {error}")
        self._refresh()
