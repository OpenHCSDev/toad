"""Native Toad conversation view for an agent-comms channel or DM."""

from __future__ import annotations

import asyncio
import os
import re
import time
from collections.abc import Mapping
from pathlib import Path

from textual import containers, on, work
from textual.app import ComposeResult
from textual.content import Content

from agent_comms import ActivityState, Thread
from agent_comms.operations import wire

from toad import messages
from toad.widgets.agent_response import AgentResponse
from toad.widgets.conversation import (
    Contents,
    ContentsGrid,
    Conversation,
    Cursor,
    CursorContainer,
    Window,
)
from toad.widgets.flash import Flash
from toad.widgets.prompt import Prompt
from toad.widgets.throbber import Throbber
from toad.widgets.user_input import UserInput


def _comms_root() -> Path:
    return Path(os.environ.get("AGENT_COMMS_ROOT", "~/.agent-comms")).expanduser()


def session_thread_name(project_path) -> str:
    """The wire thread name for a Toad project directory (ACP naming)."""
    return (
        re.sub(r"[^A-Za-z0-9_-]+", "-", Path(project_path).name or "session").strip("-")
        or "session"
    )


def resolve_session_thread(
    comms, project_path: Path, preferred: str | None = None
) -> str | None:
    """Resolve Toad's wire identity from the registry's authoritative worktree."""
    project = Path(project_path).expanduser().resolve()
    threads = comms.registry.all_threads()
    if preferred:
        preferred = comms.registry.canonical_name(preferred)
    if (
        preferred in threads
        and Path(threads[preferred].worktree).expanduser().resolve() == project
    ):
        return preferred
    matches = [
        name
        for name, thread in threads.items()
        if Path(thread.worktree).expanduser().resolve() == project
        and "acp" in thread.tags
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def _format_context(person: Mapping) -> str:
    used = person.get("context_used")
    size = person.get("context_size")
    percent = person.get("context_percent")
    if used is None or not size or percent is None:
        return ""
    return f"{used:,}/{size:,} tokens ({percent:.1f}%)"


class CommsActivity(AgentResponse):
    """An ephemeral native Markdown block describing a peer's live work."""

    DEFAULT_CLASSES = "block comms-activity"


class CommsChatView(Conversation):
    """A wire-backed conversation using Toad's normal transcript primitives."""

    BINDINGS = Conversation.BINDINGS[:5]

    def __init__(
        self,
        project_path: Path,
        *,
        target: str,
        kind: str,
        me: str,
    ) -> None:
        super().__init__(project_path)
        self.target = target
        self.kind = kind
        self._me = me
        self._seen_seqs: set[int] = set()
        self._activity_snapshot: tuple = ()
        self._refresh_lock = asyncio.Lock()

    def compose(self) -> ComposeResult:
        yield Throbber(id="throbber")
        with Window():
            with ContentsGrid():
                with CursorContainer(id="cursor-container"):
                    yield Cursor()
                with Contents(id="contents"):
                    yield containers.VerticalGroup(id="comms-activity")
        yield Flash()
        yield Prompt(
            simple_input=True,
            placeholder=f"Message {self.target}",
        ).data_bind(
            project_path=Conversation.project_path,
            working_directory=Conversation.working_directory,
            agent_info=Conversation.agent_info,
            agent_ready=Conversation.agent_ready,
            current_mode=Conversation.current_mode,
            modes=Conversation.modes,
            status=Conversation.status,
        )

    async def on_mount(self) -> None:
        self.agent_info = Content(self._target_label())
        self.agent_ready = True
        self.prepare_prompt()
        self.window.anchor()
        self.set_interval(1.0, self._refresh)
        self.call_later(self._refresh)

    def prepare_prompt(self) -> None:
        """Apply comms prompt state after a mode becomes active."""
        self.prompt.agent_info = self.agent_info
        self.prompt.agent_ready = True
        self.prompt.shell_mode = False
        self.prompt.update_prompt()
        self.prompt.focus()

    def watch_agent(self, agent) -> None:
        """Keep the inherited agent reactive from turning this into a shell session."""
        self.agent_info = Content(self._target_label())

    @work
    async def watch_agent_ready(self, ready: bool) -> None:
        """Comms readiness has no shell process to await."""

    def _target_label(self) -> str:
        if self.kind == "irc":
            return "IRC · #all"
        if self.kind == "dm":
            return f"@{self.target}"
        return self.target

    def _messages(self, comms):
        if self.kind == "irc":
            return comms.channel_history("#all")
        if self.kind == "dm":
            return comms.dm_history(self._me, self.target)
        return comms.channel_history(self.target)

    def _visible_people(self, people: list[Mapping]) -> list[Mapping]:
        peers = [person for person in people if person["name"] != self._me]
        if self.kind == "dm":
            return [person for person in peers if person["name"] == self.target]
        if self.target not in {"#all", "broadcast"} and self.kind != "irc":
            tag = self.target.removeprefix("#")
            return [person for person in peers if tag in person.get("tags", [])]
        return peers

    async def _refresh(self) -> None:
        if not self.is_attached or self._refresh_lock.locked():
            return
        try:
            if self.screen is not self.app.screen:
                return
        except Exception:
            return
        async with self._refresh_lock:
            try:
                comms = wire(_comms_root())
                messages_on_wire = list(self._messages(comms))
                people = list(comms.who())
                activity = comms.all_activity()
                if self.kind == "dm":
                    comms.acknowledge(self._me, self.target)
            except Exception as error:
                self.status = f"Wire error: {error}"
                return

            follow = self.window.scroll_y >= self.window.max_scroll_y
            tray = self.query_one("#comms-activity", containers.VerticalGroup)
            for message in messages_on_wire:
                if message.seq in self._seen_seqs:
                    continue
                stamp = time.strftime("%H:%M", time.localtime(message.timestamp))
                attribution = f"**{message.sender}** · {stamp}\n\n"
                block = (
                    UserInput(attribution + message.body)
                    if message.sender == self._me
                    else AgentResponse(attribution + message.body)
                )
                await self.contents.mount(block, before=tray)
                self._seen_seqs.add(message.seq)

            visible_people = self._visible_people(people)
            active = []
            for person in visible_people:
                current = activity.get(person["name"])
                if current is None or current.state is ActivityState.IDLE:
                    continue
                active.append((person, current))
            snapshot = tuple(
                (
                    person["name"],
                    current.state.value,
                    current.detail,
                    current.timestamp,
                    person.get("model"),
                    person.get("context_used"),
                    person.get("context_size"),
                    person.get("context_percent"),
                )
                for person, current in active
            )
            if snapshot != self._activity_snapshot:
                await tray.remove_children()
                for person, current in active:
                    metadata = " · ".join(
                        value
                        for value in (
                            person.get("model") or "",
                            _format_context(person),
                        )
                        if value
                    )
                    detail = current.detail or current.state.value
                    body = f"**@{person['name']} · {current.state.value}**\n\n{detail}"
                    if metadata:
                        body += f"\n\n`{metadata}`"
                    await tray.mount(CommsActivity(body))
                self._activity_snapshot = snapshot

            self.busy_count = len(active)
            if self.kind == "dm" and visible_people:
                person = visible_people[0]
                self.status = " · ".join(
                    value
                    for value in (person.get("model") or "", _format_context(person))
                    if value
                )
            elif active:
                self.status = f"{len(active)} active"
            else:
                self.status = ""
            if follow:
                self.window.scroll_end(animate=False)

    @on(messages.UserInputSubmitted)
    async def on_user_input_submitted(self, event: messages.UserInputSubmitted) -> None:
        event.stop()
        if not event.body.strip():
            return
        try:
            comms = wire(_comms_root())
            if self._me not in comms.registry:
                comms.register(
                    Thread(
                        name=self._me,
                        tags=frozenset({"human"}),
                        worktree=str(self.project_path),
                    )
                )
            comms.send(
                self._me, "#all" if self.kind == "irc" else self.target, event.body
            )
        except Exception as error:
            self.prompt.text = event.body
            self.flash(f"Send failed: {error}", style="error")
            return
        await self._refresh()
