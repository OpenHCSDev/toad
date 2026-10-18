"""Blocks declare cursor behavior; one component owns content selection."""
from __future__ import annotations

from abc import abstractmethod
from functools import cached_property
from typing import ClassVar
from agent_comms.declared_family import DeclaredFamily
from textual.geometry import Region
from textual.widget import Widget
from toad.block_content import BlockContent



class CursorDirection(DeclaredFamily, affix="Cursor"):
    @property
    @abstractmethod
    def step(self) -> int: ...

    @property
    @abstractmethod
    def enters_from_prompt(self) -> bool: ...

    def entry(self, length: int) -> int:
        return length - 1 if self.step < 0 else 0


class UpCursor(CursorDirection):
    step = -1
    enters_from_prompt = True


class DownCursor(CursorDirection):
    step = 1
    enters_from_prompt = False


class BlockCursor(DeclaredFamily, affix="BlockCursor"):
    def __init__(self, block):
        self.block = block

    @property
    @abstractmethod
    def selected(self) -> Widget | None: ...

    @abstractmethod
    def enter(self, direction: CursorDirection) -> bool: ...

    @abstractmethod
    def move(self, direction: CursorDirection) -> bool: ...

    @abstractmethod
    def select(self, widget: Widget) -> bool: ...

    @property
    def active(self) -> BlockCursor | None:
        return self if self.selected is not None else None

    def accepts(self, owner) -> bool:
        return owner is self.selected

    def clear(self) -> None:
        pass

    def get_clipboard_text(self) -> str | None:
        return None

    def get_prompt_text(self) -> str | None:
        return self.get_clipboard_text()

    def get_block_menu(self):
        return ()

    @property
    def allow_maximize(self) -> bool:
        return False

    def maximize(self, screen) -> None:
        pass

    @property
    def region(self) -> Region | None:
        return None

    def owns_source(self, source) -> bool:
        return False

    @property
    def visible_region(self) -> Region | None:
        return None

    def show_moved_to(self, window) -> None:
        """Scroll for a keyboard move, which can land on a block out of view."""

    def show_clicked(self, window) -> None:
        """Scroll for a click, which lands on a block that is already in view."""

    def export_render(self):
        return None


class AtomicBlockCursor(BlockCursor):
    @property
    def selected(self):
        return self.block

    def enter(self, direction):
        return True

    def move(self, direction):
        return False

    def select(self, widget):
        return widget is self.block or self.block in widget.ancestors

    def get_clipboard_text(self):
        return self.block.get_clipboard_text()

    def get_prompt_text(self):
        return self.block.get_prompt_text()

    def get_block_menu(self):
        return self.block.get_block_menu()

    @property
    def allow_maximize(self):
        return self.block.allow_maximize

    def maximize(self, screen):
        screen.maximize(self.block, container=False)
        self.block.focus()

    @property
    def region(self):
        return self.block.region

    @property
    def visible_region(self):
        geometry = self.block.screen._compositor.visible_widgets.get(self.block)
        return None if geometry is None else geometry[0]

    def show_moved_to(self, window):
        window.scroll_to_center(self.block, immediate=True)

    def show_clicked(self, window):
        # The clicked block stays where it is. Only a block taller than the
        # viewport whose top is scrolled off moves, so that its top shows.
        block, viewport = self.block.region, window.content_region
        if block.height > viewport.height and block.y < viewport.y:
            window.scroll_to_widget(self.block, top=True, immediate=True)

    def export_render(self):
        from textual._compositor import Compositor

        compositor = Compositor()
        compositor.reflow(self.block, self.block.outer_size)
        return self.block.outer_size, compositor.render_full_update()


class FragmentBlockCursor(BlockCursor):
    """The cursor inside a line history rests on one drawn message.

    The history draws messages as rows, not widgets, so the cursor holds the
    message (its fragment) and asks the history where its rows are.
    """

    def __init__(self, block):
        super().__init__(block)
        self.fragment = None

    @property
    def current(self):
        """The message the cursor rests on, while the history still draws it."""
        fragment = self.fragment
        return fragment if fragment is not None and self.block.draws_fragment(fragment) else None

    @property
    def selected(self):
        return self.block if self.current is not None else None

    def enter(self, direction):
        # The cursor arrives at the reader's side of the screen, not at an
        # end of the loaded history the reader may be far from.
        fragments = self.block.visible_fragments() or self.block.drawn_fragments
        if not fragments:
            return False
        self.fragment = fragments[direction.entry(len(fragments))]
        return True

    def move(self, direction):
        fragments = self.block.drawn_fragments
        current = self.current
        if current is None or all(current is not seen for seen in self.block.visible_fragments()):
            # The reader scrolled away from the cursor: it starts again from what they see.
            return self.enter(direction)
        index = next(index for index, drawn in enumerate(fragments) if drawn is current) + direction.step
        if 0 <= index < len(fragments):
            self.fragment = fragments[index]
            return True
        # At a loaded edge with more history beyond it the cursor waits there:
        # scrolling to it loads the next page.
        return self.block.has_older if direction.step < 0 else self.block.has_newer

    def select(self, widget):
        fragment = self.block.fragment_under_mouse(widget)
        if fragment is None:
            return False
        self.fragment = fragment
        return True

    def clear(self):
        self.fragment = None

    def get_clipboard_text(self):
        fragment = self.current
        return None if fragment is None else fragment.clipboard_text

    def get_block_menu(self):
        fragment = self.current
        return () if fragment is None else fragment.block_menu

    @property
    def region(self):
        fragment = self.current
        return None if fragment is None else self.block.fragment_region(fragment)

    visible_region = region

    def show_moved_to(self, window):
        if (fragment := self.current) is not None:
            self.block.show_fragment(fragment)


class ChildBlockCursor(BlockCursor):
    def __init__(self, block):
        super().__init__(block)
        self._child = None

    @property
    def current(self):
        return self._child if self._child in self.block.displayed_children else None

    @property
    def active(self):
        return self.current.block_cursor.active if self.current is not None else None

    @property
    def selected(self):
        cursor = self.active
        return None if cursor is None else cursor.selected

    def _enter_from(self, index, direction):
        children = self.block.displayed_children
        while 0 <= index < len(children):
            self._child = children[index]
            # An entry awaiting the original producer is still this child.
            # Only a completed empty entry permits crossing its boundary.
            if self._child.block_cursor.enter(direction):
                return True
            index += direction.step
        self._child = None
        return False

    def enter(self, direction):
        return self._enter_from(direction.entry(len(self.block.displayed_children)), direction)

    def move(self, direction):
        child = self.current
        if child is None:
            return False
        if child.block_cursor.move(direction):
            return True
        index = self.block.displayed_children.index(child) + direction.step
        return self._enter_from(index, direction)

    def select(self, widget):
        for child in self.block.displayed_children:
            if child.block_cursor.select(widget):
                self._child = child
                return True
        return False

    def clear(self):
        if self.current is not None:
            self.current.block_cursor.clear()
        self._child = None


class ConversationBlock(BlockContent):
    """Conversation content, with an owned atomic cursor by default."""

    # Saved source blocks precede this live tail; equal orders retain arrival order.
    conversation_order: ClassVar[int] = 1

    def notification_targets(self):
        return ()

    @cached_property
    def block_cursor(self) -> BlockCursor:
        return AtomicBlockCursor(self)


class ContentNavigation:
    def __init__(self, contents):
        self.contents = contents
        self._current = None

    @property
    def blocks(self):
        return self.contents.displayed_children

    @property
    def current(self) -> ConversationBlock | None:
        return self._current if self._current in self.blocks else None

    def clear(self) -> None:
        self._current = None

    @property
    def cursor(self) -> BlockCursor | None:
        return self.current.block_cursor.active if self.current is not None else None

    @property
    def selected(self):
        cursor = self.cursor
        return None if cursor is None else cursor.selected

    def move(self, direction: CursorDirection) -> None:
        blocks = self.blocks
        if not blocks:
            self.clear()
            return
        current = self.current
        if current is None:
            if not direction.enters_from_prompt:
                return
            destination = direction.entry(len(blocks))
        else:
            if current.block_cursor.move(direction):
                return
            destination = blocks.index(current) + direction.step
        while 0 <= destination < len(blocks):
            block = blocks[destination]
            if block.block_cursor.enter(direction):
                self._current = block
                return
            destination += direction.step
        if destination < 0 and current is not None:
            # At the oldest accepted block, Up clamps to its first source
            # root. Entering from Up would wrap back to its last root.
            current.block_cursor.enter(DownCursor())
        else:
            self.clear()

    def select(self, widget: Widget) -> bool:
        # Textual supplies an arbitrary descendant once at the click boundary.
        for block in self.blocks:
            if block.block_cursor.select(widget):
                self._current = block
                return True
        return False


def require_blocks(widgets):
    """Decode the Textual mount boundary once before category consumers."""
    for widget in widgets:
        if not isinstance(widget, ConversationBlock):
            raise TypeError("Conversation contents require nominal blocks")
    return widgets
