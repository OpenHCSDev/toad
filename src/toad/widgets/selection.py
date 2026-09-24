"""Pointer adapters for Textual's existing selection owners.

Focus owns widget-row selection; OptionList.highlighted owns virtual-row selection.
Hover is an input to those owners, never another independently rendered state.
"""

from textual import events, on
from textual.message import Message
from textual.widgets import ListItem, ListView, OptionList, Static


class FocusSelection(Static, can_focus=True):
    _pointer_focus = False

    def on_mouse_move(self, event: events.MouseMove) -> None:
        # Enter can be synthesized when layout changes beneath a stationary
        # pointer. Only actual pointer input may take focus from the composer.
        self._pointer_focus = True
        if not self.has_focus:
            self.focus(scroll_visible=False)

    def on_leave(self, event: events.Leave) -> None:
        if self._pointer_focus and self.has_focus:
            self.blur()
        self._pointer_focus = False

    def on_key(self, event: events.Key) -> None:
        self._pointer_focus = False


class HoverSelection(Static, can_focus=True):
    """A focusable row that highlights from CSS `:hover`.

    Taking keyboard focus on every pointer move runs the whole focus machinery
    (focus-within restyles, binding refresh). Rows only need a repaint, so
    pointer movement must not change focus.
    """


class SelectionOptionList(OptionList):
    class PointerSelected(Message):
        pass

    def _on_mouse_move(self, event: events.MouseMove) -> None:
        event.prevent_default()
        self._mouse_hovering_over = None
        index = event.style.meta.get("option")
        if isinstance(index, int) and 0 <= index < self.option_count:
            if index != self.highlighted and not self.get_option_at_index(index).disabled:
                self.highlighted = index
                self.post_message(self.PointerSelected())


class SelectionListItem(ListItem):
    @on(events.Enter)
    @on(events.Leave)
    def on_enter_or_leave(self, event: events.Enter | events.Leave) -> None:
        event.prevent_default()
        event.stop()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        self._select_pointer()

    def _select_pointer(self) -> None:
        if isinstance(self.parent, ListView):
            self.parent.index = self.parent.children.index(self)
