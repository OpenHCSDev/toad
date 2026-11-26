"""Native views of prepared rows: link actions, selection and viewport paint."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import replace
from functools import cached_property, partial
from pathlib import Path
from typing import cast

from metaclass_registry.mro_dispatch import handles
from rich.segment import Segment
from textual import on
from textual._paint_state import PaintState
from textual.events import Mount, Unmount
from textual.geometry import Region, Size
from textual.scroll_view import ScrollView
from textual.selection import Selection
from textual.strip import Strip
from textual.visual import Visual
from textual.widget import Widget
from textual.widgets._markdown import OpensMarkdownLinks

from toad.app_node import FollowsTheme
from toad.arrivals import AnimatesArrivals
from toad.block_navigation import ConversationEntry
from toad.core.events import LinkContextChanged
from toad.core.input_events import SelectHistoricalIdentity
from toad.core_event_carrier import CoreEventReceiver
from toad.frame_presentation import RowRun
from toad.client.line_blocks import LineLink
from toad.link_opening import OpensLineLinks
from toad.menus import MenuCommand, message_menu
from toad.message_rows import MessageRow
from toad.navigation_target import NavigationTarget, SelectTarget
from toad.project_link import ProjectLink
from toad.project_path_owner import ProjectPathOwner
from toad.widgets.comms_menu import ActionMenu
from toad.widgets.transcript_lines import Lines, link_place


class RestylesOnTheme(FollowsTheme):
    """Rows restyle when the theme changes; each member says how in invalidate_lines."""

    def theme_changed(self) -> None:
        self.invalidate_lines()

    @abstractmethod
    def invalidate_lines(self) -> None: ...


class ReferenceRendering(RestylesOnTheme, CoreEventReceiver):
    """Borrow the source's observation for exactly this rendering lifetime."""
    @on(Mount)
    def _on_mount(self):
        owner = ProjectPathOwner.containing(self)
        self.observe_core(self.app.coordination_access.events)
        self.observe_core(owner.link_context_events)
        self.app.coordination_access.show_references(self, owner.reference_context.requires_observation)

    @on(Unmount)
    def _on_unmount(self):
        # Textual dispatches each class's handler, including CoreEventReceiver's.
        self.app.coordination_access.show_references(self, False)

    @handles(LinkContextChanged)
    def reference_context_changed(self, event: LinkContextChanged):
        owner = ProjectPathOwner.containing(self)
        self.app.coordination_access.show_references(self, owner.reference_context.requires_observation)
        self.invalidate_lines()


class OpensLinks(OpensMarkdownLinks, CoreEventReceiver, OpensLineLinks):
    """The shared link handlers in a Textual widget: a click runs the link itself
    (OpenLineLink); the keyboard dispatches the same link."""

    def select_target(self, target: NavigationTarget) -> None:
        self.publish_core(SelectTarget(target))

    def select_historical(self, name: str, source: str) -> None:
        self.publish_core(SelectHistoricalIdentity(name, source))

    def preview_link(self, link: ProjectLink) -> None:
        self.run_worker(link.preview(self), group="open-link")

    def warn_link(self, text: str) -> None:
        self.notify(text, severity="warning")

    def run_link(self, work: Callable[[], Awaitable[None]]) -> None:
        self.run_worker(work(), group="open-link")

    def show_file(self, path: Path) -> None:
        """A kept file previews as a project file does."""
        self.app.run_worker(partial(self.app.session_navigation.preview, path, position=None))

    async def link_menu(self, href: str, event: object) -> bool:
        return await LineLink.from_href(href).copy_menu(self, event)

    def offer_path(self, event, path: Path) -> None:
        """A right-click on a file link: a menu at the click that copies its full path."""
        event.prevent_default()
        ActionMenu.show(self.screen, Region.from_offset(event.screen_offset, (0, 0)), str(path),
                        [(partial(self.app.copy_to_clipboard, str(path)), "Copy full path")])


class MessageRowBlock(OpensLinks):
    """A widget that is one bus message under the cursor: it offers the message's menu."""

    message_row: MessageRow

    def get_block_menu(self) -> tuple[MenuCommand, ...]:
        return message_menu(self.message_row)


def selection_painted(widget: Widget, strip: Strip, row: int) -> Strip:
    """Project the live selection onto drawn rows, never onto shared preparation."""
    selection = widget.text_selection
    if selection is None:
        return strip
    span = selection.get_span(row)
    if span is None:
        return strip
    start, end = span
    if end == -1:
        end = strip.cell_length
    start, end = max(0, start), min(end, strip.cell_length)
    # Strip.divide yields only pieces before each cut; its end retains the tail.
    cuts = sorted({cut for cut in (start, end, strip.cell_length) if 0 < cut <= strip.cell_length})
    pieces = strip.divide(cuts) if cuts else [strip]
    head, body, tail = [], [], []
    position = 0
    for piece in pieces:
        following = position + piece.cell_length
        if following <= start:
            head.append(piece)
        elif position >= end:
            tail.append(piece)
        else:
            body.append(piece)
        position = following
    if not body:
        return strip
    selection_style = Visual.selection_style(widget).rich_style
    if selection_style is None:
        return strip
    painted = Strip(
        list(Segment.apply_style(Strip.join(body), None, selection_style)),
        sum(piece.cell_length for piece in body),
    )
    return Strip.join((*head, painted, *tail))


class LinkedRows(OpensLinks, RowRun):
    """Draw prepared rows on the native background, using their window's shared arrival fade."""

    _arrival_entry: ConversationEntry | None = None
    _arrival_window: AnimatesArrivals | None = None

    @cached_property
    def link_place(self) -> int:
        """What tells the links these rows draw apart from equal links drawn elsewhere."""
        return link_place()

    @on(Mount)
    def on_mount(self) -> None:
        ancestors = cast(Widget, self).ancestors_with_self
        self._arrival_entry = next((node for node in ancestors if isinstance(node, ConversationEntry)), None)
        self._arrival_window = next((node for node in ancestors if isinstance(node, AnimatesArrivals)), None)

    @property
    @abstractmethod
    def line_sets(self) -> tuple[Lines, ...]:
        """The prepared rows this widget draws, which its selection copies."""

    def get_selection(self, selection: Selection) -> tuple[str, str]:
        rows = "\n".join("".join(segment.text for segment in row).rstrip()
                         for lines in self.line_sets for row in lines)
        return selection.extract(rows), "\n"

    def on_background(self, strip: Strip, paint: PaintState, y: int, x: int = 0) -> Strip:
        """Apply this entry's shared arrival fade and the widget's current background."""
        window, entry = self._arrival_window, self._arrival_entry
        if window is not None and entry is not None and window.has_active_arrivals:
            mix = window.arrival_frame(entry, self.row_position(y))
            if mix is not None:
                strip = self.app.colours.paint_rising(
                    replace(mix, start=entry.text_background), strip
                )
        return strip.apply_style(paint.rich_style).apply_offsets(x, y)

    def blank_row(self, width: int, paint: PaintState) -> Strip:
        return Strip.blank(width, paint.rich_style)


class HorizontalRows(LinkedRows, ScrollView):
    """Prepared rows use Textual's horizontal viewport when code is unwrapped."""

    def get_content_width(self, container, viewport) -> int:
        return max((lines.content_width for lines in self.line_sets), default=0)

    def _size_updated(self, size, virtual_size, container_size, layout=True) -> bool:
        lines = self.line_sets
        self.set_reactive(Widget.virtual_size, Size(
            max((item.content_width for item in lines), default=0),
            sum(item.height for item in lines),
        ))
        return super()._size_updated(size, virtual_size, container_size, layout)

    def on_background(self, strip: Strip, paint: PaintState, y: int, x: int = 0) -> Strip:
        start = self.scroll_offset.x
        x += len(strip.crop(0, start).text) if start else 0
        return super().on_background(strip.crop(start, start + self.scrollable_content_region.width), paint, y, x)
