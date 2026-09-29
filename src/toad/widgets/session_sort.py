from toad.preferences import SidebarSettings

"""Shared sorting control for model-owned channel and member ordering."""

import asyncio
from pathlib import Path

from agent_comms.display_order import ChannelSort, ThreadSort
from textual import events
from textual.geometry import Offset
from textual.widgets import Static

from toad.widgets.comms_menu import ContextMenu


class SortControl[Order: (ThreadSort, ChannelSort)](Static, can_focus=True):
    BINDINGS = [("enter,space", "choose_sort", "Sort")]
    DEFAULT_CSS = """
    SortControl {
        width: auto;
        max-width: 60%;
        height: 1;
        margin-left: 1;
        text-wrap: nowrap;
        text-overflow: ellipsis;
        color: $text-muted;
        pointer: pointer;
    }
    SortControl:hover, SortControl:focus { color: $text; text-style: underline; }
    """

    def __init__(self, order: Order, scope: str):
        super().__init__()
        self.scope = scope
        self.order = order

    def update_order(self, order: Order) -> None:
        if order != self.order:
            self.order = order
            self._update_label()

    def on_mount(self):
        self._update_label()

    def _set_label(self, label: str, tooltip: str) -> None:
        """Only text changes can invalidate this auto-width control's layout."""
        if self.content != label:
            self.update(label)
        if self.tooltip != tooltip:
            self.tooltip = tooltip

    def _update_label(self) -> None:
        label = self.order.label
        self._set_label(f"{label} ▾", f"Sort {self.scope} by {label.lower()}")

    def action_choose_sort(self):
        selected = self.selected_order.value if self.selected_order is not None else None
        choices = {order.value: order.label for order in type(self.order)}

        def choose(value: str):
            if value in choices:
                self.run_worker(self._save_order(type(self.order)(value)))
            else:
                self.choose_extra(value)

        title = f"Sort {self.scope}"
        items = [
            (key, ("✓ " if key == selected else "  ") + label)
            for key, label in choices.items()
        ]
        items.extend(self.extra_items())
        menu_width = max(len(title), *(len(label) for _, label in items)) + 4
        self.app.push_screen(
            ContextMenu(
                Offset(self.region.right - menu_width, self.region.bottom),
                title,
                items,
            ),
            choose,
        )

    @property
    def selected_order(self):
        """The checked choice, or None for a control spanning mixed orders."""
        return self.order

    def extra_items(self) -> list[tuple[str, str]]:
        return []

    def choose_extra(self, value: str) -> None:
        pass

    async def _save_order(self, order: Order) -> None:
        try:
            self.update_order(await self.persist_order(order))
        except (OSError, ValueError) as error:
            self.notify(str(error), title="Channel sort", severity="error")

    async def persist_order(self, order: Order) -> Order:
        raise NotImplementedError

    def on_click(self, event: events.Click):
        event.stop()
        if event.button == 1:
            self.action_choose_sort()


class SessionSort(SortControl[ThreadSort]):
    def __init__(self, channel: str):
        self.channel = channel
        super().__init__(ThreadSort.CREATED, channel)

    async def persist_order(self, order: ThreadSort) -> ThreadSort:
        from toad.comms_root import implicit_root, run_selected_write

        comms = self.app.coordination_access.service
        source_root = self.screen.coordination_root
        if source_root is None:
            from toad.widgets.comms_sidebar import CommsSidebar

            sidebar = self.screen.query_one_optional(CommsSidebar)
            source_root = sidebar.observation.service.root if sidebar is not None and sidebar.observation.service is not None else None
        if source_root is not None and comms.root.resolve() != Path(source_root).resolve():
            raise ValueError("Comms route changed before sorting")
        channel = await asyncio.to_thread(
            run_selected_write, comms.root, comms.channels.set_channel_sort,
            self.channel, order, implicit=implicit_root(),
        )
        return channel.order


class ChannelListSort(SortControl[ChannelSort]):
    def __init__(self):
        super().__init__(ChannelSort.NAME, "channels")

    async def persist_order(self, order: ChannelSort) -> ChannelSort:
        from toad.comms_root import implicit_root, run_selected_write

        comms = self.app.coordination_access.service
        source_root = self.screen.coordination_root
        if source_root is None:
            from toad.widgets.comms_sidebar import CommsSidebar

            sidebar = self.screen.query_one_optional(CommsSidebar)
            source_root = sidebar.observation.service.root if sidebar is not None and sidebar.observation.service is not None else None
        if source_root is not None and comms.root.resolve() != Path(source_root).resolve():
            raise ValueError("Comms route changed before sorting")
        return await asyncio.to_thread(
            run_selected_write, comms.root, comms.channels.set_channel_order,
            order, implicit=implicit_root(),
        )

    _visibility_fields = (SidebarSettings.show_stopped, SidebarSettings.show_archived)

    def extra_items(self) -> list[tuple[str, str]]:
        return [
            (field.name, ("✓ " if field.__get__(self.app.settings.sidebar) else "  ") + field.title)
            for field in self._visibility_fields
        ]

    def choose_extra(self, value: str) -> None:
        for field in self._visibility_fields:
            if field.name == value:
                group = self.app.settings.sidebar
                field.__set__(group, not field.__get__(group))
                self.run_worker(self.app.save_settings(), group="channel-visibility")
                return
