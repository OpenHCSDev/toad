"""Blocks declare cursor behavior; one component owns content selection."""
from abc import abstractmethod
from functools import cached_property
from agent_comms.declared_family import DeclaredFamily
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
    def enter(self, direction: CursorDirection) -> None: ...

    @abstractmethod
    def move(self, direction: CursorDirection) -> Widget | None: ...

    @abstractmethod
    def select(self, widget: Widget) -> None: ...


class AtomicBlockCursor(BlockCursor):
    @property
    def selected(self):
        return self.block

    def enter(self, direction):
        pass

    def move(self, direction):
        return None

    def select(self, widget):
        pass


class ChildBlockCursor(BlockCursor):
    def __init__(self, block):
        super().__init__(block)
        self.index = -1

    @property
    def selected(self):
        children = self.block.displayed_children
        return children[self.index] if 0 <= self.index < len(children) else None

    def enter(self, direction):
        self.index = direction.entry(len(self.block.displayed_children))

    def move(self, direction):
        self.index += direction.step
        return self.selected

    def select(self, widget):
        self.index = self.block.displayed_children.index(widget)


class ConversationBlock(BlockContent):
    """Nominal content admission, with an owned atomic cursor by default."""
    @cached_property
    def block_cursor(self) -> BlockCursor:
        return AtomicBlockCursor(self)


class ContentNavigation:
    def __init__(self, contents):
        self.contents = contents
        self.index = -1

    @property
    def blocks(self):
        return self.contents.displayed_children

    @property
    def current(self) -> ConversationBlock | None:
        return self.blocks[self.index] if 0 <= self.index < len(self.blocks) else None

    @property
    def selected(self):
        return self.current.block_cursor.selected if self.current is not None else None

    def move(self, direction: CursorDirection) -> None:
        blocks = self.blocks
        if not blocks:
            self.index = -1
            return
        if self.index == -1:
            if not direction.enters_from_prompt:
                return
            self.index = direction.entry(len(blocks))
        else:
            if self.current is not None and self.current.block_cursor.move(direction) is not None:
                return
            destination = self.index + direction.step
            if destination < 0:
                self.current.block_cursor.enter(direction)
                return
            if destination >= len(blocks):
                self.index = -1
                return
            self.index = destination
        self.current.block_cursor.enter(direction)

    def select(self, widget: Widget) -> bool:
        # Textual supplies an arbitrary descendant once at the click boundary.
        for block in self.blocks:
            child = widget
            while child is not block and child.parent is not None:
                child = child.parent
            if child is block:
                self.index = self.blocks.index(block)
                if widget is not block:
                    direct = widget
                    while direct.parent is not block:
                        direct = direct.parent
                    block.block_cursor.select(direct)
                return True
        return False


def admitted_blocks(widgets):
    """Decode the Textual mount boundary once before category consumers."""
    for widget in widgets:
        if not isinstance(widget, ConversationBlock):
            raise TypeError("Conversation contents require nominal blocks")
    return widgets
