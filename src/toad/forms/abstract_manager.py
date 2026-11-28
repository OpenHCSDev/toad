"""Textual OpenHCS ``AbstractManager`` widget over ``formbridge.managers``.

Polymorphic Textual counterpart to ``pyqt_reactive``'s ``AbstractManagerWidget``:
inherits ``formbridge.managers.AbstractManager`` directly so item CRUD, selection
preservation, ``ObjectState`` dirty/provenance visual tracking, and cohort flashing
through ``FlashCoordinator`` + ``TextualFlashSurface`` run once in ``formbridge``.
"""

from __future__ import annotations

import asyncio
from abc import ABCMeta
from collections.abc import Callable, Coroutine, Sequence
from concurrent.futures import Future
from typing import Any, ClassVar

from formbridge.animation.flash_coordinator import FlashCoordinator
from formbridge.managers.abstract_manager import (
    AbstractManager,
    ManagerListSurface,
    ManagerVisualSurface,
)
from formbridge.services.host_services import UiHostServices
from textual import containers, events, on
from textual.app import ComposeResult
from textual.message import Message
from textual.message_pump import _MessagePumpMeta
from textual.widgets import Button, Label, ListItem, ListView, Static

from toad.forms.flash_surface import TextualFlashSurface
from toad.textual_colours import ThemedApp


class TextualAbstractMeta(_MessagePumpMeta, ABCMeta):
    """Combines Textual's message-pump metaclass with ``abc.ABCMeta``."""


class TextualHostServices(UiHostServices):
    """``UiHostServices`` implementation backed by a mounted Textual widget/app."""

    def __init__(self, widget: containers.Vertical) -> None:
        self._widget = widget
        self.main_window = widget

    def get_current_color_scheme(self) -> Any:
        if self._widget.is_mounted and isinstance(self._widget.app, ThemedApp):
            return self._widget.app.colours.scheme
        return None

    def show_error_dialog(self, error_message: str, title: str = "Error") -> None:
        if self._widget.is_mounted:
            self._widget.app.notify(error_message, title=title, severity="error")

    def show_info_dialog(self, info_message: str, title: str = "Information") -> None:
        if self._widget.is_mounted:
            self._widget.app.notify(info_message, title=title)

    def execute_async_operation(
        self,
        async_func: Callable[..., Coroutine[Any, Any, Any]],
        *args: Any,
        **kwargs: Any,
    ) -> Future:
        future: Future = Future()

        async def _runner() -> None:
            try:
                result = await async_func(*args, **kwargs)
            except Exception as error:  # noqa: BLE001
                if not future.done():
                    future.set_exception(error)
            else:
                if not future.done():
                    future.set_result(result)

        asyncio.ensure_future(_runner())
        return future


class TextualManagerListItem(ListItem):
    """One row inside ``TextualAbstractManagerWidget``'s ``ListView``."""

    def __init__(self, label_text: str, data: Any, *, scope_id: str = "") -> None:
        super().__init__(Label(label_text, markup=False))
        self.manager_data = data
        self.scope_id = scope_id
        self._label_text = label_text

    def set_row_text(self, label_text: str) -> None:
        self._label_text = label_text
        if self.is_mounted:
            self.query_one(Label).update(label_text)


class TextualManagerListSurface(ManagerListSurface):
    """``ManagerListSurface`` adapter over a Textual ``ListView``."""

    def __init__(
        self,
        list_view: ListView,
        on_selection: Callable[[Any], None],
    ) -> None:
        self._list_view = list_view
        self._on_selection = on_selection

    def _rows(self) -> list[TextualManagerListItem]:
        return [
            child
            for child in self._list_view.children
            if isinstance(child, TextualManagerListItem)
        ]

    def row_count(self) -> int:
        return len(self._rows())

    def row_item_at(self, index: int) -> Any:
        rows = self._rows()
        if 0 <= index < len(rows):
            return rows[index]
        return None

    def row_item_data(self, row_item: Any) -> Any:
        return row_item.manager_data if isinstance(row_item, TextualManagerListItem) else None

    def selected_row_items(self) -> Sequence[Any]:
        highlighted = self._list_view.highlighted_child
        if isinstance(highlighted, TextualManagerListItem):
            return (highlighted,)
        return ()

    def select_row_item(self, row_item: Any) -> None:
        rows = self._rows()
        if row_item in rows:
            self._list_view.index = rows.index(row_item)

    def scroll_to_row_item(self, row_item: Any) -> None:
        if isinstance(row_item, TextualManagerListItem) and row_item.is_mounted:
            self._list_view.scroll_to_widget(row_item, animate=False)

    def emit_selection(self, payload: Any) -> None:
        self._on_selection(payload)


class TextualManagerVisualSurface(ManagerVisualSurface):
    """``ManagerVisualSurface`` driving Textual ``call_later`` + ``TextualFlashSurface``."""

    def __init__(
        self,
        host: TextualAbstractManagerWidget,
        flash_surface: TextualFlashSurface,
    ) -> None:
        self._host = host
        self._flash_surface = flash_surface

    def schedule_flush(self, callback: Callable[[], None]) -> None:
        if self._host.is_mounted:
            self._host.call_later(callback)
        else:
            callback()

    def on_scope_visual_update(self, scope_id: str, changed_paths: set[str]) -> None:
        del changed_paths
        self._host.refresh_scope_row(scope_id)

    def on_flash_batch(self, scope_ids: Sequence[str]) -> None:
        self._flash_surface.queue_flash(scope_ids)


class TextualAbstractManagerWidget(
    AbstractManager,
    containers.Vertical,
    metaclass=TextualAbstractMeta,
):
    """Textual OpenHCS list manager widget backed by ``formbridge.managers.AbstractManager``."""

    ACTION_BUTTONS: ClassVar[tuple[tuple[str, str], ...]] = (
        ("edit", "Edit"),
        ("delete", "Delete"),
    )

    class SelectionChanged(Message):
        def __init__(self, manager: TextualAbstractManagerWidget, payload: Any) -> None:
            super().__init__()
            self.manager = manager
            self.payload = payload

    class ItemsChanged(Message):
        def __init__(self, manager: TextualAbstractManagerWidget) -> None:
            super().__init__()
            self.manager = manager

    class StatusChanged(Message):
        def __init__(self, manager: TextualAbstractManagerWidget, text: str) -> None:
            super().__init__()
            self.manager = manager
            self.text = text

    def __init__(
        self,
        *,
        flash_coordinator: FlashCoordinator | None = None,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self._title_label = Static(self.TITLE, markup=False)
        self._status_label = Static("", markup=False)
        self._list_view = ListView()
        self._action_buttons: dict[str, Button] = {
            action_id: Button(label, id=f"manager-action-{action_id}", compact=True)
            for action_id, label in self.ACTION_BUTTONS
        }
        self._host_services = TextualHostServices(self)
        self._list_surface = TextualManagerListSurface(
            self._list_view,
            lambda payload: self.post_message(self.SelectionChanged(self, payload)),
        )
        coordinator = flash_coordinator if flash_coordinator is not None else FlashCoordinator()
        self.flash_surface = TextualFlashSurface(self, coordinator=coordinator)
        self._visual_surface = TextualManagerVisualSurface(self, self.flash_surface)
        self._scope_rows: dict[str, TextualManagerListItem] = {}
        self._init_manager_core(flash_coordinator=coordinator)

    def compose(self) -> ComposeResult:
        yield self._title_label
        with containers.HorizontalGroup():
            for button in self._action_buttons.values():
                yield button
        yield self._list_view
        yield self._status_label

    @on(events.Mount)
    def _mount_manager(self) -> None:
        self.update_item_list()
        self.update_button_states()

    @on(events.Unmount)
    def _unmount_manager(self) -> None:
        self.flash_surface.dispose()
        self.dispose_manager()

    @on(ListView.Highlighted)
    def _row_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view is self._list_view:
            self.handle_selection_changed()

    @on(ListView.Selected)
    def _row_selected(self, event: ListView.Selected) -> None:
        if event.list_view is self._list_view:
            self.handle_item_activated(event.item)

    @on(Button.Pressed)
    def _action_pressed(self, event: Button.Pressed) -> None:
        for action_id, button in self._action_buttons.items():
            if event.button is button:
                event.stop()
                self.handle_button_action(action_id)
                return

    def list_surface(self) -> ManagerListSurface:
        return self._list_surface

    def visual_surface(self) -> ManagerVisualSurface:
        return self._visual_surface

    def host_services(self) -> UiHostServices:
        return self._host_services

    def format_item_label(self, item: Any) -> str:
        """Render one row's label including live ``ObjectState`` dirty markers."""
        base = str(item)
        dirty = self.dirty_fields_for(item)
        return f"{base} ●" if dirty else base

    def row_data_for_item(self, item: Any, index: int) -> Any:
        return self.ITEM_HOOKS.list_item_data_for(item, index)

    def update_item_list(self) -> None:
        """Rebuild the Textual ``ListView`` rows and rebind ``TextualFlashSurface`` targets."""
        self._list_view.clear()
        self._scope_rows.clear()
        targets: dict[str, TextualManagerListItem] = {}
        for index, item in enumerate(self.manager_items):
            scope_id = self.scope_for_item(item)
            if scope_id:
                self.subscribe_scope_visuals(scope_id)
            row = TextualManagerListItem(
                self.format_item_label(item),
                self.row_data_for_item(item, index),
                scope_id=scope_id,
            )
            self._list_view.append(row)
            if scope_id:
                self._scope_rows[scope_id] = row
                targets[scope_id] = row
        self.flash_surface.bind_targets(targets)
        self.update_button_states()

    def refresh_scope_row(self, scope_id: str) -> None:
        """Repaint one row's label after its ``ObjectState`` changed."""
        row = self._scope_rows.get(scope_id)
        if row is None:
            return
        item = self._item_from_row_data(row.manager_data)
        if item is not None:
            row.set_row_text(self.format_item_label(item))

    def emit_items_changed(self) -> None:
        self.post_message(self.ItemsChanged(self))

    def emit_status(self, message: str) -> None:
        self._status_label.update(message)
        self.post_message(self.StatusChanged(self, message))

    def update_button_states(self) -> None:
        has_selection = bool(self.selected_items())
        for action_id in ("edit", "delete"):
            if button := self._action_buttons.get(action_id):
                button.disabled = not has_selection
