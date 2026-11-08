"""Blocks declare cursor behavior; one component owns content selection."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Iterable, Sequence
from functools import cached_property
from typing import TYPE_CHECKING, Callable, ClassVar, cast

from agent_comms.nominal.declared_family import DeclaredFamily
from agent_comms.read_basis import DisplayCut, NoDisplaySelection
from agent_comms.ui_model.message_category import MessageCategory, OtherCategory
from textual.app import App
from textual.geometry import Spacing
from textual.message import Message
from textual.widget import Widget
from ui_theme.effects import TextFade  # type: ignore[import-untyped]

from toad.block_content import BlockContent
from toad.frame_presentation import ARRIVAL, CascadingRows
from toad.notification_status import MessageQueueEntry
from toad.widgets.presentation_window import UNPLACED, NewerEnd, OlderEnd, PageEnd, Placed, Unplaced, arranged
from toad.widgets.transcript_fragments import NO_REST, CursorRest
from textual.events import Mount
from textual import on

if TYPE_CHECKING:
    from agent_comms.message_reference import MessageReference
    from agent_comms.ui_model.message_category import AgentActivityBoundary
    from textual.screen import Screen

    from toad.widgets.history_anchor import HistoryWindow
    from toad.widgets.transcript_history import LineHistory
    from toad.widgets.conversation import Conversation
    from toad.widgets.transcript_fragments import TranscriptFragment


class CursorDirection(PageEnd, DeclaredFamily, affix="Cursor"):
    @abstractmethod
    def from_prompt(self, length: int) -> int:
        """The block a move from the prompt enters; past the end when it enters none."""


class UpCursor(OlderEnd, CursorDirection):
    def from_prompt(self, length: int) -> int:
        return self.entry(length)


class DownCursor(NewerEnd, CursorDirection):
    def from_prompt(self, length: int) -> int:
        return length


class BlockCursor(DeclaredFamily, affix="BlockCursor"):
    def __init__(self, block):
        self.block = block

    @abstractmethod
    def accepts(self, owner: Widget) -> bool:
        """Whether `owner` is the widget this cursor selects."""

    @abstractmethod
    def enter(self, direction: CursorDirection) -> bool: ...

    @abstractmethod
    def move(self, direction: CursorDirection) -> bool: ...

    @abstractmethod
    def select(self, widget: Widget) -> bool: ...

    @property
    def active(self) -> BlockCursor:
        return self if self.selected_widgets else NoBlockCursor()

    @property
    @abstractmethod
    def selected_widgets(self) -> tuple[Widget, ...]:
        """Each cursor derives its widget selection from its own source membership."""
        ...

    def present(self, conversation: Conversation, show: Callable[[BlockCursor], None]) -> None:
        """A selected block receives keyboard focus before its deferred paint."""
        conversation.screen.set_focus(conversation.window)
        conversation.call_after_refresh(conversation._present_block_cursor, self, show)

    def clear(self) -> None:
        pass

    def get_clipboard_text(self) -> str:
        return ""

    def get_prompt_text(self) -> str:
        return self.get_clipboard_text()

    def get_block_menu(self):
        return ()

    @property
    def allow_maximize(self) -> bool:
        return False

    def maximize(self, screen: Screen) -> None:
        pass

    @property
    def region(self) -> Unplaced:
        return UNPLACED

    def owns_source(self, source) -> bool:
        return False

    @property
    def visible_region(self) -> Unplaced:
        return UNPLACED

    def show_moved_to(self, window: HistoryWindow) -> None:
        """Scroll for a keyboard move, which can land on a block out of view."""

    def show_clicked(self, window: HistoryWindow) -> None:
        """Scroll for a click, which lands on a block that is already in view."""
        self.region.reveal_clicked(window)

    def export_to_svg(self, conversation: Conversation) -> None:
        """Only a cursor resting on one drawn block has something to export."""


class NoBlockCursor(BlockCursor):
    """An empty selection keeps the reader anchored and returns focus to its prompt."""

    def __init__(self) -> None:
        pass

    def accepts(self, owner: Widget) -> bool:
        return False

    selected_widgets = ()

    @property
    def active(self) -> BlockCursor:
        return self

    def enter(self, direction: CursorDirection) -> bool:
        return False

    def move(self, direction: CursorDirection) -> bool:
        return False

    def select(self, widget: Widget) -> bool:
        return False

    def present(self, conversation: Conversation, show: Callable[[BlockCursor], None]) -> None:
        conversation.window.anchor()
        conversation.prompt.focus()


class AtomicBlockCursor(BlockCursor):
    @property
    def selected_widgets(self) -> tuple[Widget, ...]:
        return (self.block,)

    def accepts(self, owner: Widget) -> bool:
        return owner is self.block

    def enter(self, direction: CursorDirection):
        return True

    def move(self, direction: CursorDirection):
        return False

    def select(self, widget: Widget):
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

    def maximize(self, screen: Screen):
        screen.maximize(self.block, container=False)
        self.block.focus()

    @property
    def region(self):
        return Placed(self.block.region)

    @property
    def visible_region(self):
        return arranged(self.block)

    def show_moved_to(self, window: HistoryWindow):
        window.scroll_to_center(self.block, immediate=True)

    def export_to_svg(self, conversation: Conversation) -> None:
        from textual._compositor import Compositor

        compositor = Compositor()
        compositor.reflow(self.block, self.block.outer_size)
        conversation.open_render_as_svg(self.block.outer_size, compositor.render_full_update())


class FragmentBlockCursor(BlockCursor):
    """The cursor inside a line history rests on one drawn message.

    The history draws messages as rows, not widgets, so the cursor holds the
    message (its fragment) and asks the history where its rows are.
    """

    def __init__(self, block: LineHistory):
        super().__init__(block)
        self.fragment: CursorRest = NO_REST

    @property
    def current(self) -> CursorRest:
        """Where the cursor rests while this history draws it."""
        return self.fragment.drawn_in(self.block)

    @property
    def selected_fragments(self) -> tuple[TranscriptFragment, ...]:
        """The source occurrence the cursor owns while this history draws it."""
        return self.current.rested

    @property
    def selected_widgets(self) -> tuple[Widget, ...]:
        return tuple(self.block for _ in self.selected_fragments)

    def accepts(self, owner: Widget) -> bool:
        return self.current.selects(owner, self.block)

    def enter(self, direction: CursorDirection):
        # The cursor arrives at the reader's side of the screen, not at an
        # end of the loaded history the reader may be far from.
        fragments = self.block.visible_fragments() or self.block.drawn_fragments
        if not fragments:
            return False
        self.fragment = fragments[direction.entry(len(fragments))]
        return True

    def move(self, direction: CursorDirection):
        fragments = self.block.drawn_fragments
        current = self.current
        if not any(current is seen for seen in self.block.visible_fragments()):
            # The reader scrolled away from the cursor: it starts again from what they see.
            return self.enter(direction)
        index = (
            next(index for index, drawn in enumerate(fragments) if drawn is current)
            + direction.step
        )
        if 0 <= index < len(fragments):
            self.fragment = fragments[index]
            return True
        # At a loaded edge with more history beyond it the cursor waits there:
        # scrolling to it loads the next page.
        return direction.visible_more(self.block)

    def select(self, widget: Widget):
        return self.block.fragment_under_mouse(widget).selected_by(self)

    def clear(self):
        self.fragment = NO_REST

    def get_clipboard_text(self):
        return self.current.clipboard_text

    def get_block_menu(self):
        return self.current.block_menu

    @property
    def region(self):
        return self.current.placement_in(self.block)

    visible_region = region

    def show_moved_to(self, window: HistoryWindow):
        self.current.show_in(self.block)

    def show_clicked(self, window: HistoryWindow):
        self.current.show_head(self, window)

    async def show_clicked_head(self, fragment: TranscriptFragment, window: HistoryWindow) -> None:
        head = await self.block.reveal_message_head(fragment, lambda: self.fragment is fragment)
        if head is not fragment and self.fragment is fragment:
            self.fragment = head
            window.refresh(layout=True)


class ChildBlockCursor(BlockCursor):
    def __init__(self, block):
        super().__init__(block)
        self._child: ConversationEntry | AbsentEntry = NO_ENTRY

    @property
    def current(self) -> ConversationEntry | AbsentEntry:
        return self._child if self._child in self.block.displayed_children else NO_ENTRY

    @property
    def active(self):
        return self.current.block_cursor.active

    def accepts(self, owner: Widget) -> bool:
        return self.active.accepts(owner)

    @property
    def selected_widgets(self) -> tuple[Widget, ...]:
        return self.active.selected_widgets

    def _enter_from(self, index: int, direction: CursorDirection):
        children = self.block.displayed_children
        while 0 <= index < len(children):
            self._child = children[index]
            # An entry awaiting the original producer is still this child.
            # Only a completed empty entry permits crossing its boundary.
            if self._child.block_cursor.enter(direction):
                return True
            index += direction.step
        self._child = NO_ENTRY
        return False

    def enter(self, direction: CursorDirection):
        return self._enter_from(
            direction.entry(len(self.block.displayed_children)), direction
        )

    def move(self, direction: CursorDirection):
        child = self.current
        return child.block_cursor.move(direction) or child.enter_next(self, direction)

    def select(self, widget: Widget):
        for child in self.block.displayed_children:
            if child.block_cursor.select(widget):
                self._child = child
                return True
        return False

    def clear(self):
        self.current.block_cursor.clear()
        self._child = NO_ENTRY


class ConversationEntry(CascadingRows, BlockContent):
    """Conversation content, with an owned atomic cursor by default.

    The rows drawn inside an entry paint its fades (`LinkedRows.arrival`), and report
    themselves as the runs those fades play across (`CascadingRows.row_runs`).
    """

    # Saved source blocks precede this live tail; equal orders retain arrival order.
    conversation_order: ClassVar[int] = 1

    def apply_message_filter(self, selected: frozenset[type[MessageCategory]]) -> None:
        self.set_display_constraint("message-category", OtherCategory in selected)

    def starts_agent_activity(self, boundary: AgentActivityBoundary) -> bool:
        return OtherCategory.observe(boundary)

    def redraw(self) -> None:
        # The widgets inside the entry draw its rows.
        for widget in cast(Widget, self).walk_children(with_self=True):
            widget.repaint_lines()

    def notification_targets(self):
        return ()

    def notification_identity_for(self, references: frozenset[MessageReference]) -> DisplayCut:
        """Live entries have no captured BUS display cut; source rows override with theirs."""
        return NoDisplaySelection()

    async def reload_notification_source(self) -> None:
        """Live entries read no page, so no display cut of theirs can go stale."""

    def queue_entries(self) -> Iterable[MessageQueueEntry]:
        """Live entries supply no captured BUS delivery rows; source rows override with theirs."""
        return ()

    @cached_property
    def block_cursor(self) -> BlockCursor:
        return AtomicBlockCursor(self)

    @property
    def endpoints(self) -> tuple[Widget, ...]:
        return (cast(Widget, self),)

    def enter_next(self, cursor: ChildBlockCursor, direction: CursorDirection) -> bool:
        return cursor._enter_from(cursor.block.displayed_children.index(self) + direction.step, direction)

    def destination(self, blocks: Sequence[ConversationEntry], direction: CursorDirection) -> int:
        return blocks.index(self) + direction.step


class AbsentEntry:
    """The cursor rests on no conversation entry: it selects, expands and protects nothing."""

    block_cursor: ClassVar[BlockCursor] = NoBlockCursor()
    # The widgets an interaction rests on, which a commit must not retire.
    endpoints: ClassVar[tuple[Widget, ...]] = ()

    def can_expand(self) -> bool:
        return False

    def is_block_expanded(self) -> bool:
        return False

    def enter_next(self, cursor: ChildBlockCursor, direction: CursorDirection) -> bool:
        """Enter the child after this one; with no child there is none."""
        return False

    def destination(self, blocks: Sequence[ConversationEntry], direction: CursorDirection) -> int:
        """The block a move from here enters: from the prompt, since the cursor rests on none."""
        return direction.from_prompt(len(blocks))


NO_ENTRY = AbsentEntry()


class CategorizedBlock(ConversationEntry):
    """An entry whose declared category owns filtering and activity grouping."""

    @property
    @abstractmethod
    def message_category(self) -> type[MessageCategory]:
        ...

    def apply_message_filter(self, selected: frozenset[type[MessageCategory]]) -> None:
        self.set_display_constraint(
            "message-category", self.message_category in selected
        )

    def starts_agent_activity(self, boundary: AgentActivityBoundary) -> bool:
        return self.message_category.observe(boundary)


class ConversationBlock(ConversationEntry):
    """A live entry: its rows rise into their own colours row after row as it appears.

    The same cascade the saved pages use, so a live arrival and a saved one reveal
    alike and a following window holds its tail above both (`UnrisenRows`). As one
    block-wide fade, a tall message appeared whole and the tail sat at its bottom
    while the text was still rising.
    """

    text_fades: ClassVar[tuple[TextFade, ...]] = (ARRIVAL,)

    if TYPE_CHECKING:
        # Every live block is a widget: the host class supplies its message pump.
        def post_message(self, message: Message) -> bool: ...

    class Mounted(Message):
        """A live block mounted; the history window around it keeps it as a reader holder."""

        def __init__(self, block: Widget) -> None:
            super().__init__()
            self.block = block

    @on(Mount)
    def on_mount(self) -> None:
        for fade in self.text_fades:
            self.run_effect(fade)
        # A live block is always mounted as a widget; the mixin cannot say so to the type checker.
        self.post_message(self.Mounted(cast(Widget, self)))


class SeparatedBlock(ConversationBlock, Widget):
    """Native blocks keep separation outside their borders, not inside body rows."""

    def _post_register(self, app: App) -> None:
        super()._post_register(app)
        self.styles.margin = Spacing(0, 1, 1, 0)


class ContentNavigation:
    def __init__(self, contents):
        self.contents = contents
        self._current: ConversationEntry | AbsentEntry = NO_ENTRY

    @property
    def blocks(self):
        return self.contents.displayed_children

    @property
    def current(self) -> ConversationEntry | AbsentEntry:
        return self._current if self._current in self.blocks else NO_ENTRY

    def accepts_menu_owner(self, owner: Widget) -> bool:
        return self.current.block_cursor.accepts(owner)

    def clear(self) -> None:
        self._current = NO_ENTRY

    @property
    def cursor(self) -> BlockCursor:
        return self.current.block_cursor.active

    def move(self, direction: CursorDirection) -> None:
        blocks = self.blocks
        if not blocks:
            self.clear()
            return
        current = self.current
        if current.block_cursor.move(direction):
            return
        destination = current.destination(blocks, direction)
        while 0 <= destination < len(blocks):
            block = blocks[destination]
            if block.block_cursor.enter(direction):
                self._current = block
                return
            destination += direction.step
        if destination < 0:
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


def require_blocks(widgets: tuple[Widget, ...]):
    """Decode the Textual mount boundary once before category consumers."""
    for widget in widgets:
        if not isinstance(widget, ConversationEntry):
            raise TypeError("Conversation contents require nominal blocks")
    return widgets
