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

    def source_regions(self):
        return ()

    def region_for(self, source) -> Region | None:
        return None

    def owns_source(self, source) -> bool:
        return False

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
    """One source selection across detached paint and actual native controls."""

    def __init__(self, block):
        super().__init__(block)
        self._selection: MarkdownSourceBlock | CursorDirection | None = None

    @property
    def selected(self):
        if self._selection is None or self.block._closing:
            return None
        if isinstance(self._selection, CursorDirection):
            sources = self._current_sources()
            if sources is None:
                return None
            direction = self._selection
            if not self._enter_from(sources, direction.entry(len(sources)), direction):
                return None
        original = self._selection
        document = self.block.document
        if (self.block._pending_source != original.document.source
                or document is not None and not original.document.same_source(document)):
            self._selection = None
            return None
        # A selected source outlives rows and native controls. Reconstruction
        # may borrow it, but only admitted paint can replace its placement.
        sources = self._current_sources()
        if sources is None:
            return original
        for source in sources:
            if self._same_member(source, original):
                self._selection = source
                return source
        self._selection = None
        return None

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

    @staticmethod
    def _same_member(left, right):
        return (left.source_index == right.source_index
                and left.document.same_source(right.document))

    def _scene_roots(self):
        from textual.widgets._markdown import MarkdownBlock

        measurement = self.block._body_measurement
        if (measurement.dormant or not measurement.ready(self.block)
                or not self.block.is_attached or self.block._closing):
            return None
        return tuple(child for child in self.block.displayed_children
                     if isinstance(child, MarkdownBlock) and child.source_block is not None)

    def _current_sources(self):
        paint = self._current_paint()
        if paint is not None:
            return tuple(source for source in paint.roots if source.placement is not None)
        roots = self._scene_roots()
        return None if roots is None else tuple(root.source_block for root in roots)

    def _scene_block(self):
        source = self.selected
        roots = self._scene_roots()
        if source is not None and roots is not None:
            return next((root for root in roots
                         if self._same_member(root.source_block, source)), None)

    def _enter_from(self, sources, index, direction):
        if 0 <= index < len(sources):
            self._selection = sources[index]
            return True
        self._selection = None
        return False

    def enter(self, direction):
        if self.block._closing:
            return False
        sources = self._current_sources()
        if sources is None:
            # Retain the original entry, not a guessed root from stale paint.
            # Source requests revoke it through this cursor's clear().
            self._selection = direction
            return True
        return self._enter_from(sources, direction.entry(len(sources)), direction)

    def move(self, direction):
        source = self.selected
        if source is None:
            return isinstance(self._selection, CursorDirection)
        sources = self._current_sources()
        if sources is None:
            # Copy retains the original selected source while new paint
            # prepares. It does not admit another root through stale geometry.
            return True
        index = next(index for index, member in enumerate(sources)
                     if self._same_member(member, source)) + direction.step
        return self._enter_from(sources, index, direction)

    def select(self, widget):
        roots = self._scene_roots()
        if roots is None:
            return False
        for ancestor in (widget, *widget.ancestors):
            if ancestor in roots:
                self._selection = ancestor.source_block
                return True
        return False

    def accepts(self, owner):
        source = self.selected
        return (source is not None and isinstance(owner, type(source))
                and self._same_member(source, owner))

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
        source = self.selected
        return None if source is None else self.region_for(source)

    def source_regions(self):
        """Original displayed source members and their current screen regions."""
        compositor = self.block.screen._compositor
        placements = compositor._published_map
        paint = self._current_paint()
        if paint is not None:
            geometry = placements.get(self.block)
            if geometry is None:
                return ()
            return tuple((source, source.placement.region.translate(geometry.region.offset))
                         for source in paint.roots if source.placement is not None)
        roots = self._scene_roots()
        return () if roots is None else tuple((root.source_block, geometry.region)
                                              for root in roots
                                              if (geometry := placements.get(root)) is not None)

    def region_for(self, source):
        return next((region for member, region in self.source_regions()
                     if self._same_member(member, source)), None)

    def owns_source(self, source):
        document = self.block.get_current_document()
        return document is not None and document.same_source(source.document)

    @property
    def visible_region(self):
        scene = self._scene_block()
        if scene is not None:
            geometry = scene.screen._compositor.visible_widgets.get(scene)
            return None if geometry is None else geometry[0].intersection(geometry[1])
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

        scene = self._scene_block()
        if scene is not None:
            if self.region_for(scene.source_block) is None:
                return None
            from textual._compositor import Compositor

            compositor = Compositor()
            compositor.reflow(scene, scene.outer_size)
            return scene.outer_size, compositor.render_full_update()
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
