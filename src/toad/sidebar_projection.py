"""Keyed channel hierarchy, row paint and spinner custody."""
from __future__ import annotations
import asyncio
from textual.content import Content
from toad.sidebar_preparation import ThreadRowInput, ThreadRowsWork
from toad.sidebar_snapshot import SidebarSnapshot
from toad.widgets.activity_spinner import FRAMES

class SidebarProjection:
    def __init__(self, sidebar):
        self.sidebar = sidebar
        self.snapshot = None
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

    def painted_busy_rows(self):
        """Animate only rows admitted by the current native paint scene.

        Navigation owns the whole roster. Its attachment walk is not an
        animation census, and offscreen rows have no spinner pixels to paint.
        Read the compositor's existing visible custody without retaining a
        competing row list or busy-state index.
        """
        from toad.widgets.comms_sidebar import CommsRow
        for row in self.sidebar.screen._compositor.visible_widgets:
            if isinstance(row, CommsRow) and row.has_class("-busy"):
                if row.is_navigation_row() and row.sidebar_owner() is self.sidebar:
                    yield row

    @property
    def thread_rows(self):
        from toad.widgets.comms_sidebar import ChannelGroup
        return [row for group in self.sidebar.children if isinstance(group, ChannelGroup)
                for row in group.member_container.children]

    @property
    def session_rows(self):
        return [row for row in self.thread_rows if row.has_open_view()]

    def mount(self) -> None:
        self.timer = self.sidebar.set_interval(
            1 / self.sidebar.app.settings.sidebar.spinner_frames_per_second,
            self.animate, pause=True,
        )

    def update_animation_cadence(self) -> None:
        if self.timer is not None:
            self.timer.stop()
            self.mount()
            self.sync_spinner()

    def pause_spinner(self) -> None:
        if self.timer is not None:
            self.timer.pause()

    def has_snapshot(self) -> bool:
        return self.snapshot is not None

    def sync_spinner(self) -> None:
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
        for row in self.painted_busy_rows():
            row.advance_spinner(self.phase)

    async def publish(self, snapshot: SidebarSnapshot) -> None:
        service = self.sidebar.observation.service
        async with self.lock:
            if self.sidebar.observation.service is not service or not self.sidebar.accepts_publication():
                return
            # The snapshot is source custody, not a paint signature. Keyed
            # groups and prepared rows own changes to their actual output.
            await self.rebuild(snapshot)
            if not self.sidebar.accepts_publication():
                return
            if not self.sidebar.navigation.ready.is_set() and self.sidebar.is_attached and self.sidebar.screen.is_current:
                self.sidebar.call_after_refresh(self.sidebar.navigation.finish, self.sidebar.navigation.revision)

    async def rebuild(self, snapshot: SidebarSnapshot) -> None:
        if not self.sidebar.accepts_publication():
            return
        self.snapshot = snapshot
        row_inputs = await ThreadRowsWork.capture(
            self.sidebar.app.preparation,
            tuple(ThreadRowInput(person) for person in snapshot.all_people.values()),
        )
        if not self.sidebar.accepts_publication():
            return
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
        retired_channels = set(channels) - set(desired_keys)
        for key in retired_channels:
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
        if retired_channels or new_groups:
            self.sidebar.navigation.rows_changed()
        for view in snapshot.wire.channels:
            channel_row = channels[view.channel.name]
            unread = snapshot.wire.channel_unread.get(view.channel.name, 0)
            channel_row.set_label(f"{'* ' if view.channel.pinned else ''}{view.channel.name}")
            group = channel_row.query_ancestor(ChannelGroup)
            group.update_unread(unread)
            group.update_activity(view, row_inputs)
            channel_row.set_class(bool(unread), "-unread")
            await group.present(view)
            if not self.sidebar.accepts_publication():
                return
        ordered = [self.sidebar.query_one(NewSessionButton), *(
            channels[key].query_ancestor(ChannelGroup) for key in desired_keys
        )]
        if list(self.sidebar.children) != ordered:
            positions = {widget: index for index, widget in enumerate(ordered)}
            self.sidebar.sort_children(key=positions.__getitem__)
            self.sidebar.navigation.rows_changed()
        self.sidebar.navigation.apply()
        self.sidebar.navigation.mode_changed(self.sidebar.app.selected_mode)
        self.sync_spinner()
        # Retain full row text. Only the content grows; the outer sidebar owns
        # both native scrollbars and keeps their geometry at the visible edge.
        widest = max((Content(view.channel.name).cell_length + 12
                      for view in snapshot.wire.channels), default=0)
        if row_inputs.rows:
            widest = max(widest, row_inputs.content_width + 8)
        widest = min(widest, 512)
        panel = self.sidebar.query_ancestor(SideBarCollapsible)
        if widest != self.horizontal_width:
            self.horizontal_width = widest
            panel.styles.min_width = widest
