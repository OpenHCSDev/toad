"""Native Toad conversation view for an agent-comms channel or DM."""

from __future__ import annotations

import asyncio
import os
import re
import time
from collections.abc import Mapping
from pathlib import Path

from agent_comms import ActivityState, MessagePage, Thread
from agent_comms import Message as WireMessage
from agent_comms.operations import wire
from textual import containers, on, work
from textual.app import ComposeResult
from textual.content import Content
from textual.widget import Widget

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

HISTORY_PAGE_SIZE = 40
HISTORY_WINDOW_SIZE = 120
HISTORY_PAGE_BYTES = 256 * 1024
HISTORY_EDGE_THRESHOLD = 2


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
        self._history: list[tuple[WireMessage, Widget]] = []
        self._has_older = False
        self._has_newer = False
        self._history_initialized = False
        self._poll_cursor = 0
        self._edge_load_scheduled = False
        self._activity_snapshot: tuple = ()
        self._refresh_lock = asyncio.Lock()

    def compose(self) -> ComposeResult:
        with Window():
            with ContentsGrid():
                with CursorContainer(id="cursor-container"):
                    yield Cursor()
                with Contents(id="contents"):
                    yield containers.VerticalGroup(id="comms-activity")
        yield Flash()
        with containers.Vertical(id="prompt-stack"):
            yield Throbber(id="throbber")
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
        self.watch(self.window, "scroll_y", self._on_window_scroll, init=False)
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

    def _message_page(
        self,
        comms,
        *,
        before: int | None = None,
        after: int | None = None,
    ) -> MessagePage:
        if self.kind == "irc":
            target = "#all"
        elif self.kind == "dm":
            return comms.dm_history_page(
                self._me,
                self.target,
                before=before,
                after=after,
                limit=HISTORY_PAGE_SIZE,
                max_bytes=HISTORY_PAGE_BYTES,
            )
        else:
            target = self.target
        return comms.channel_history_page(
            target,
            before=before,
            after=after,
            limit=HISTORY_PAGE_SIZE,
            max_bytes=HISTORY_PAGE_BYTES,
        )

    def _message_block(self, message: WireMessage) -> Widget:
        stamp = time.strftime("%H:%M", time.localtime(message.timestamp))
        attribution = f"**{message.sender}** · {stamp}\n\n"
        if message.sender == self._me:
            return UserInput(attribution + message.body)
        return AgentResponse(attribution + message.body)

    async def _mount_page(self, page: MessagePage, *, older: bool) -> None:
        mounted = {message.seq for message, _ in self._history}
        records = [message for message in page.messages if message.seq not in mounted]
        if not records:
            if older:
                self._has_older = page.has_older
            else:
                self._has_newer = page.has_newer
            return

        pairs = [(message, self._message_block(message)) for message in records]
        anchor = self._history[0][1] if older and self._history else None
        anchor_y = anchor.region.y if anchor is not None else None
        tray = self.query_one("#comms-activity", containers.VerticalGroup)
        before = self._history[0][1] if older and self._history else tray
        await self.contents.mount(*(widget for _, widget in pairs), before=before)

        if older:
            self._history[0:0] = pairs
            self._has_older = page.has_older
            while len(self._history) > HISTORY_WINDOW_SIZE:
                _, widget = self._history.pop()
                await widget.remove()
                self._has_newer = True
        else:
            self._history.extend(pairs)
            self._has_newer = page.has_newer
            while len(self._history) > HISTORY_WINDOW_SIZE:
                _, widget = self._history.pop(0)
                await widget.remove()
                self._has_older = True

        if anchor is not None and anchor_y is not None:
            self.call_after_refresh(self._restore_anchor, anchor, anchor_y)

    def _restore_anchor(self, anchor: Widget, screen_y: int) -> None:
        if anchor.is_attached:
            self.window.scroll_relative(
                y=anchor.region.y - screen_y,
                animate=False,
                immediate=True,
            )

    def _on_window_scroll(self, scroll_y: float) -> None:
        if not self._history_initialized or self._edge_load_scheduled:
            return
        near_top = scroll_y <= HISTORY_EDGE_THRESHOLD and self._has_older
        near_bottom = (
            self.window.max_scroll_y - scroll_y <= HISTORY_EDGE_THRESHOLD
            and self._has_newer
        )
        if near_top or near_bottom:
            self._edge_load_scheduled = True
            self.call_later(self._load_history_edge)

    async def _load_history_edge(self) -> None:
        try:
            if not self._history or self._refresh_lock.locked():
                return
            async with self._refresh_lock:
                comms = wire(_comms_root())
                if self.window.scroll_y <= HISTORY_EDGE_THRESHOLD and self._has_older:
                    page = self._message_page(comms, before=self._history[0][0].seq)
                    await self._mount_page(page, older=True)
                elif (
                    self.window.max_scroll_y - self.window.scroll_y
                    <= HISTORY_EDGE_THRESHOLD
                    and self._has_newer
                ):
                    page = self._message_page(comms, after=self._history[-1][0].seq)
                    await self._mount_page(page, older=False)
        except Exception as error:
            self.status = f"Wire error: {error}"
        finally:
            self._edge_load_scheduled = False

    async def _refresh_history(self, comms) -> bool:
        """Refresh the bounded history window; return whether to follow the end."""
        follow = (
            not self._has_newer and self.window.scroll_y >= self.window.max_scroll_y
        )
        high_water = comms.message_high_water()
        if not self._history_initialized:
            page = self._message_page(comms)
            await self._mount_page(page, older=False)
            self._has_older = page.has_older
            self._history_initialized = True
            self._poll_cursor = high_water
            return True

        if high_water <= self._poll_cursor:
            return follow

        page = self._message_page(comms, after=self._poll_cursor)
        if page.messages and follow:
            await self._mount_page(page, older=False)
            self._poll_cursor = (
                page.newest_seq if page.has_newer else high_water
            ) or high_water
        else:
            if page.messages:
                self._has_newer = True
            self._poll_cursor = high_water
        return follow

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
                people = list(comms.who())
                activity = comms.all_activity()
                follow = await self._refresh_history(comms)
                if self.kind == "dm":
                    comms.acknowledge(self._me, self.target)
            except Exception as error:
                self.status = f"Wire error: {error}"
                return

            tray = self.query_one("#comms-activity", containers.VerticalGroup)
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
