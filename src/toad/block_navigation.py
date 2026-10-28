"""Blocks declare cursor behavior; one component owns content selection."""

from __future__ import annotations

from abc import abstractmethod
from functools import cached_property
from typing import TYPE_CHECKING, Callable, ClassVar, cast

from agent_comms.declared_family import DeclaredFamily
from agent_comms.ui_model.message_category import MessageCategory, OtherCategory
from textual.geometry import Region
from textual.widget import Widget
from ui_theme.effects import NEW_TEXT, Fade, Mix  # type: ignore[import-untyped]

from toad.block_content import BlockContent
from toad.frame_presentation import AnimationEffects
from toad.widgets.presentation_window import NewerEnd, OlderEnd, PageEnd

if TYPE_CHECKING:
    from agent_comms.ui_model.message_category import AgentActivityBoundary
    from textual.screen import Screen

    from toad.widgets.history_anchor import HistoryWindow
    from toad.widgets.transcript_history import LineHistory
    from toad.widgets.conversation import Conversation
    from toad.widgets.transcript_fragments import TranscriptFragment


class CursorDirection(PageEnd, DeclaredFamily, affix="Cursor"):
    @property
    @abstractmethod
    def enters_from_prompt(self) -> bool: ...


class UpCursor(OlderEnd, CursorDirection):
    enters_from_prompt = True


class DownCursor(NewerEnd, CursorDirection):
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
    def active(self) -> BlockCursor:
        return self if self.selected is not None else NoBlockCursor()

    @property
    def selected_widgets(self) -> tuple[Widget, ...]:
        selected = self.selected
        return () if selected is None else (selected,)

    def present(self, conversation: Conversation, show: Callable[[BlockCursor], None]) -> None:
        """A selected block receives keyboard focus before its deferred paint."""
        conversation.screen.set_focus(conversation.window)
        conversation.call_after_refresh(conversation._present_block_cursor, self, show)

    def accepts(self, owner: Widget) -> bool:
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

    def maximize(self, screen: Screen) -> None:
        pass

    @property
    def region(self) -> Region | None:
        return None

    def owns_source(self, source) -> bool:
        return False

    @property
    def visible_region(self) -> Region | None:
        return None

    def show_moved_to(self, window: HistoryWindow) -> None:
        """Scroll for a keyboard move, which can land on a block out of view."""

    def show_clicked(self, window: HistoryWindow) -> None:
        """Scroll for a click, which lands on a block that is already in view."""
        region = self.region
        if region is not None and window.message_head_hidden(region.height, region.y):
            window.release_anchor()
            window.scroll_relative(
                y=region.y - window.scrollable_content_region.y,
                animate=False, immediate=True,
            )

    def export_render(self):
        return None


class NoBlockCursor(BlockCursor):
    """An empty selection keeps the reader anchored and returns focus to its prompt."""

    def __init__(self) -> None:
        pass

    @property
    def selected(self) -> None:
        return None

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
    def selected(self):
        return self.block

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
        return self.block.region

    @property
    def visible_region(self):
        geometry = self.block.screen._compositor.visible_widgets.get(self.block)
        return None if geometry is None else geometry[0]

    def show_moved_to(self, window: HistoryWindow):
        window.scroll_to_center(self.block, immediate=True)

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

    def __init__(self, block: LineHistory):
        super().__init__(block)
        self.fragment = None

    @property
    def selected_fragments(self) -> tuple[TranscriptFragment, ...]:
        """The source occurrence the cursor owns while this history draws it."""
        fragment = self.fragment
        return (
            (fragment,)
            if fragment is not None and self.block.draws_fragment(fragment)
            else ()
        )

    @property
    def current(self):
        """The optional scalar view used by block navigation."""
        return next(iter(self.selected_fragments), None)

    @property
    def selected(self):
        return self.block if self.current is not None else None

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
        if current is None or all(
            current is not seen for seen in self.block.visible_fragments()
        ):
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

    def show_moved_to(self, window: HistoryWindow):
        if (fragment := self.current) is not None:
            self.block.show_fragment(fragment)

    def show_clicked(self, window: HistoryWindow):
        if (fragment := self.current) is not None:
            self.block.run_worker(
                self._show_clicked(fragment, window), group="message-heading", exclusive=True,
            )

    async def _show_clicked(self, fragment, window: HistoryWindow) -> None:
        head = await self.block.reveal_message_head(
            fragment, lambda: self.fragment is fragment,
        )
        if head is not None and self.fragment is fragment:
            self.fragment = head
            window.refresh(layout=True)


class ChildBlockCursor(BlockCursor):
    def __init__(self, block):
        super().__init__(block)
        self._child = None

    @property
    def current(self):
        return self._child if self._child in self.block.displayed_children else None

    @property
    def active(self):
        return self.current.block_cursor.active if self.current is not None else NoBlockCursor()

    @property
    def selected(self):
        return self.active.selected

    def _enter_from(self, index: int, direction: CursorDirection):
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

    def enter(self, direction: CursorDirection):
        return self._enter_from(
            direction.entry(len(self.block.displayed_children)), direction
        )

    def move(self, direction: CursorDirection):
        child = self.current
        if child is None:
            return False
        if child.block_cursor.move(direction):
            return True
        index = self.block.displayed_children.index(child) + direction.step
        return self._enter_from(index, direction)

    def select(self, widget: Widget):
        for child in self.block.displayed_children:
            if child.block_cursor.select(widget):
                self._child = child
                return True
        return False

    def clear(self):
        if self.current is not None:
            self.current.block_cursor.clear()
        self._child = None


class ConversationEntry(AnimationEffects[Mix], BlockContent):
    """Conversation content, with an owned atomic cursor by default.

    The rows drawn inside an entry paint its fades (`LinkedRows.arrival`).
    """

    # Saved source blocks precede this live tail; equal orders retain arrival order.
    conversation_order: ClassVar[int] = 1

    def apply_message_filter(self, selected: frozenset[type[MessageCategory]]) -> None:
        self.set_display_constraint("message-category", OtherCategory in selected)

    def starts_agent_activity(self, boundary: AgentActivityBoundary) -> bool:
        return OtherCategory.observe(boundary)

    def repaint(self) -> None:
        # The widgets inside the entry draw its rows.
        for widget in cast(Widget, self).walk_children(with_self=True):
            widget.refresh()

    def notification_targets(self):
        return ()

    @cached_property
    def block_cursor(self) -> BlockCursor:
        return AtomicBlockCursor(self)


class CategorizedBlock(ConversationEntry):
    """An entry whose declared category owns filtering and activity grouping."""

    @property
    def message_category(self) -> type[MessageCategory]:
        raise NotImplementedError

    def apply_message_filter(self, selected: frozenset[type[MessageCategory]]) -> None:
        self.set_display_constraint(
            "message-category", self.message_category in selected
        )

    def starts_agent_activity(self, boundary: AgentActivityBoundary) -> bool:
        return self.message_category.observe(boundary)


class ConversationBlock(ConversationEntry):
    """A live entry: it fades into its own colours as it appears."""

    text_fades: ClassVar[tuple[Fade, ...]] = (NEW_TEXT,)

    def on_mount(self) -> None:
        for fade in self.text_fades:
            self.run_effect(fade)


class ContentNavigation:
    def __init__(self, contents):
        self.contents = contents
        self._current = None

    @property
    def blocks(self):
        return self.contents.displayed_children

    @property
    def current(self) -> ConversationEntry | None:
        return self._current if self._current in self.blocks else None

    def accepts_menu_owner(self, owner: Widget) -> bool:
        for block in self.blocks:
            if block is self._current:
                return block.block_cursor.accepts(owner)
        return False

    def clear(self) -> None:
        self._current = None

    @property
    def cursor(self) -> BlockCursor:
        return self.current.block_cursor.active if self.current is not None else NoBlockCursor()

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


def require_blocks(widgets: tuple[Widget, ...]):
    """Decode the Textual mount boundary once before category consumers."""
    for widget in widgets:
        if not isinstance(widget, ConversationEntry):
            raise TypeError("Conversation contents require nominal blocks")
    return widgets
