"""Keyed channel hierarchy, row paint and spinner custody."""
from __future__ import annotations
import asyncio
from dataclasses import dataclass
from textual.content import Content
from toad.sidebar_snapshot import SidebarSnapshot
from toad.widgets.activity_spinner import FRAMES

@dataclass(frozen=True)
class SidebarPaint:
    snapshot: SidebarSnapshot
    expansion: tuple[tuple[str, bool], ...]
    actions: tuple[tuple[str, str], ...]

class SidebarProjection:
    def __init__(self, sidebar):
        self.sidebar = sidebar
        self.snapshot = None
        self.paint = None
        self.lock = asyncio.Lock()
        self.phase = 0
        self.timer = None
        self.horizontal_width = 0

    @property
    def channels(self):
        from toad.widgets.comms_sidebar import ChannelGroup
        return {group.row.target_name: group.row for group in self.sidebar.children
                if isinstance(group, ChannelGroup)}

    @property
    def rows(self):
        from toad.widgets.comms_sidebar import ChannelGroup
        return [row for group in self.sidebar.children if isinstance(group, ChannelGroup)
                for row in (group.row, *group.member_container.children)
                if row.is_navigation_row()]

    @property
    def thread_rows(self):
        from toad.widgets.comms_sidebar import ChannelGroup
        return [row for group in self.sidebar.children if isinstance(group, ChannelGroup)
                for row in group.member_container.children]

    @property
    def session_rows(self):
        return [row for row in self.thread_rows if row.has_open_view()]

    def mount(self) -> None:
        self.timer = self.sidebar.set_interval(.18, self.animate, pause=True)

    def pause_spinner(self) -> None:
        if self.timer is not None:
            self.timer.pause()

    def has_snapshot(self) -> bool:
        return self.snapshot is not None

    def sync_spinner(self, snapshot: SidebarSnapshot | None = None) -> None:
        timer = self.timer
        if timer is None:
            return
        active = self.sidebar.shows_rows() and self.sidebar.observation.enabled
        if active and self.has_snapshot() and any(row.has_class("-busy") for row in self.rows):
            timer.resume()
        else:
            timer.pause()

    def animate(self) -> None:
        if not self.sidebar.shows_rows() or self.snapshot is None:
            self.sync_spinner()
            return
        self.phase = (self.phase + 1) % len(FRAMES)
        for row in self.rows:
            if row.has_class("-busy"):
                row.advance_spinner(self.phase)

    async def publish(self, snapshot: SidebarSnapshot) -> None:
        service = self.sidebar.observation.service
        async with self.lock:
            if self.sidebar.observation.service is not service or not self.sidebar.accepts_publication():
                return
            changed = snapshot != self.snapshot
            paint = SidebarPaint(snapshot, tuple(self.sidebar.navigation.state.expanded.items()),
                                 tuple(self.sidebar.app.thread_actions.pending.items()))
            if paint != self.paint:
                # Publication is serialized by this sidebar, not a global paint
                # mask held across worker delivery and descendant mount awaits.
                await self.rebuild(snapshot)
                if not self.sidebar.accepts_publication():
                    return
                self.paint = paint
                if changed:
                    self.sidebar.app.open_tabs_changed.publish(None)
            else:
                self.sidebar.navigation.apply()
                self.sidebar.navigation.mode_changed(self.sidebar.app.selected_mode)
                self.sync_spinner(snapshot)
            if not self.sidebar.navigation.ready.is_set() and self.sidebar.is_attached and self.sidebar.screen.is_current:
                self.sidebar.call_after_refresh(self.sidebar.navigation.finish, self.sidebar.navigation.revision)

    async def rebuild(self, snapshot: SidebarSnapshot) -> None:
        if not self.sidebar.accepts_publication():
            return
        self.snapshot = snapshot
        channels = self.channels
        from toad.widgets.comms_sidebar import CommsRow, ChannelGroup, NewSessionButton
        from toad.navigation_target import channel_target
        from toad.widgets.session_sort import ChannelListSort
        from toad.widgets.side_bar import SideBarCollapsible

        control = self.sidebar.query_ancestor(SideBarCollapsible).header_control
        assert isinstance(control, ChannelListSort)
        control.update_order(snapshot.wire.channel_order)
        desired_keys = [
            view.channel.name
            for view in snapshot.wire.channels
        ]
        if not self.sidebar.query(NewSessionButton):
            await self.sidebar.mount(NewSessionButton())
            if not self.sidebar.accepts_publication():
                return
        for key in set(channels) - set(desired_keys):
            row = channels.pop(key)
            await row.query_ancestor(ChannelGroup).remove()
            if not self.sidebar.accepts_publication():
                return
        new_groups: list[ChannelGroup] = []
        for key in desired_keys:
            if key not in channels:
                row = channels[key] = CommsRow(channel_target(key), key)
                new_groups.append(ChannelGroup(
                    row, expanded=self.sidebar.navigation.state.expanded.get(key, row.target.expanded_by_default),
                ))
        if new_groups:
            await self.sidebar.mount(*new_groups)
            if not self.sidebar.accepts_publication():
                return
        for view in snapshot.wire.channels:
            channel_row = channels[view.channel.name]
            unread = snapshot.wire.channel_unread.get(view.channel.name, 0)
            channel_row.set_label(f"{'* ' if view.channel.pinned else ''}{view.channel.name}")
            group = channel_row.query_ancestor(ChannelGroup)
            group.update_unread(unread)
            group.update_activity(view, snapshot.all_people)
            channel_row.set_class(bool(unread), "-unread")
            await group.present(view, snapshot)
            if not self.sidebar.accepts_publication():
                return
        ordered = [self.sidebar.query_one(NewSessionButton), *(
            channels[key].query_ancestor(ChannelGroup) for key in desired_keys
        )]
        if list(self.sidebar.children) != ordered:
            positions = {widget: index for index, widget in enumerate(ordered)}
            self.sidebar.sort_children(key=positions.__getitem__)
        self.sidebar.navigation.apply(force=True)
        self.sidebar.navigation.mode_changed(self.sidebar.app.selected_mode, force=True)
        self.sync_spinner(snapshot)
        # Retain full row text. Only the content grows; the outer sidebar owns
        # both native scrollbars and keeps their geometry at the visible edge.
        widest = max((Content(view.channel.name).cell_length + 12
                      for view in snapshot.wire.channels), default=0)
        widest = max(widest, max((Content(person.presentation.label).cell_length + 8
                                  for person in snapshot.all_people.values()), default=0))
        widest = max(widest, max((Content(person.presentation.summary).cell_length + 8
                                  for person in snapshot.all_people.values()), default=0))
        widest = min(widest, 512)
        panel = self.sidebar.query_ancestor(SideBarCollapsible)
        if widest != self.horizontal_width:
            self.horizontal_width = widest
            panel.styles.min_width = widest

