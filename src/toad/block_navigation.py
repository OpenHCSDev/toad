"""Blocks declare cursor behavior; one component owns content selection."""
from __future__ import annotations

from abc import abstractmethod
from functools import cached_property
from typing import TYPE_CHECKING
from agent_comms.declared_family import DeclaredFamily
from textual.geometry import Region
from textual.widget import Widget
from toad.block_content import BlockContent

if TYPE_CHECKING:
    from textual.document._markdown import MarkdownSourceBlock


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
    def selected(self) -> Widget | MarkdownSourceBlock | None: ...

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

    @property
    def visible_region(self) -> Region | None:
        return None

    def scroll_to_center(self, window) -> None:
        pass

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

    def scroll_to_center(self, window):
        window.scroll_to_center(self.block, immediate=True)

    def export_render(self):
        from textual._compositor import Compositor

        compositor = Compositor()
        compositor.reflow(self.block, self.block.outer_size)
        return self.block.outer_size, compositor.render_full_update()


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
            # Only a completed empty admission permits crossing its boundary.
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


class DocumentBlockCursor(BlockCursor):
    """Select original grammar roots; native paint supplies their placement.

    The ordinal is a position in that exact source cohort, not a token ID.
    Source identity fences it before a new presentation's roots may supply
    geometry. Neither paint nor a second root collection is retained here.
    """

    def __init__(self, block):
        super().__init__(block)
        self._selection: tuple[int, MarkdownSourceBlock] | CursorDirection | None = None

    @property
    def selected(self):
        if self._selection is None or self.block._closing:
            return None
        if isinstance(self._selection, CursorDirection):
            paint = self._current_paint()
            if paint is None:
                return None
            direction = self._selection
            if not self._enter_from(paint, direction.entry(len(paint.roots)), direction):
                return None
        index, original = self._selection
        document = self.block.document
        if (self.block._pending_source != original.document.source
                or document is not None and not original.document.same_source(document)):
            self._selection = None
            return None
        # A selected source outlives rows and native controls. Reconstruction
        # may borrow it, but only admitted paint can replace its placement.
        paint = self._current_paint()
        if paint is None:
            return original
        if not original.document.same_source(paint.document) or not 0 <= index < len(paint.roots):
            self._selection = None
            return None
        source = paint.roots[index]
        if source.source_index != original.source_index or source.placement is None:
            self._selection = None
            return None
        self._selection = index, source
        return source

    @property
    def active(self):
        source = self.selected
        return self if source is not None or isinstance(self._selection, CursorDirection) else None

    def clear(self):
        self._selection = None

    def _current_paint(self):
        paint = self.block.block_document_paint
        width = self.block._body_measurement.width + self.block.styles.gutter.width
        return paint if paint is not None and paint.is_current(self.block, width) else None

    def _enter_from(self, paint, index, direction):
        while 0 <= index < len(paint.roots):
            source = paint.roots[index]
            # Native displayed-child admission excludes CSS-hidden/unplaced
            # roots. The original producer owns that answer, not paint leaves.
            if source.placement is not None:
                self._selection = index, source
                return True
            index += direction.step
        self._selection = None
        return False

    def enter(self, direction):
        if self.block._closing:
            return False
        paint = self._current_paint()
        if paint is None:
            # Retain the original entry, not a guessed root from stale paint.
            # Source requests revoke it through this cursor's clear().
            self._selection = direction
            return True
        return self._enter_from(paint, direction.entry(len(paint.roots)), direction)

    def move(self, direction):
        source = self.selected
        if source is None:
            return isinstance(self._selection, CursorDirection)
        paint = self._current_paint()
        if paint is None:
            # Copy retains the original selected source while new paint
            # prepares. It does not admit another root through stale geometry.
            return True
        index = self._selection[0] + direction.step
        return self._enter_from(paint, index, direction)

    def select(self, widget):
        # Pointer dispatch acquires actual native controls first. This source
        # cursor never fabricates a widget or guesses a root from paint leaves.
        return False

    def accepts(self, owner):
        source = self.selected
        return (source is not None and isinstance(owner, type(source))
                and source.source_index == owner.source_index
                and source.document.same_source(owner.document))

    def get_clipboard_text(self):
        source = self.selected
        return None if source is None else source.declaration.source_copy(source)

    def get_prompt_text(self):
        source = self.selected
        return None if source is None else source.declaration.source_copy(source, prompt=True)

    def get_block_menu(self):
        source = self.selected
        return () if source is None else source.declaration.source_block_menu(source)

    def _placement(self):
        source = self.selected
        paint = self._current_paint()
        if source is None or paint is None:
            return None
        return source.placement

    @property
    def region(self):
        placement = self._placement()
        return None if placement is None else placement.region.translate(self.block.region.offset)

    @property
    def visible_region(self):
        placement = self._placement()
        geometry = self.block.screen._compositor.visible_widgets.get(self.block)
        if placement is None or geometry is None:
            return None
        region, clip = geometry
        return placement.region.intersection(placement.clip).translate(region.offset).intersection(clip)

    def scroll_to_center(self, window):
        region = self.region
        if region is not None:
            window.scroll_to_region(
                region.translate(window.scroll_offset - window.scrollable_content_region.offset),
                center=True, immediate=True,
            )

    def export_render(self):
        from textual.strip import StripRenderable

        placement = self._placement()
        if placement is None:
            return None
        paint = self.block.block_document_paint
        region = placement.region.intersection(paint.size.region)
        if not region:
            return None
        return region.size, StripRenderable(paint.render_lines(region), region.width)


class ConversationBlock(BlockContent):
    """Nominal content admission, with an owned atomic cursor by default."""
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
            # At the oldest admitted block, Up clamps to its first source
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


def admitted_blocks(widgets):
    """Decode the Textual mount boundary once before category consumers."""
    for widget in widgets:
        if not isinstance(widget, ConversationBlock):
            raise TypeError("Conversation contents require nominal blocks")
    return widgets
