"""Native views of prepared rows: link actions, selection and viewport paint."""

from __future__ import annotations

from abc import abstractmethod
from typing import cast

from agent_comms.display_references import ChannelDisplayReference, HistoricalDisplayReference, ThreadDisplayReference
from metaclass_registry.mro_dispatch import MroDispatch, handles
from rich.segment import Segment
from textual._paint_state import PaintState
from textual.geometry import Size
from textual.scroll_view import ScrollView
from textual.selection import Selection
from textual.strip import Strip
from textual.visual import Visual
from textual.widget import Widget

from toad.block_navigation import ConversationEntry
from toad.core.events import LinkContextChanged
from toad.core.input_events import SelectHistoricalIdentity, SelectTarget
from toad.core_event_carrier import CoreEventReceiver
from toad.frame_presentation import AnimationEffects
from toad.line_blocks import LineLink, OpenHistoricalTarget, OpenReference, OpenTarget
from toad.menus import MenuItem
from toad.message_rows import MessageRow
from toad.navigation_target import NavigationTarget
from toad.project_link import ProjectLink
from toad.project_path_owner import ProjectPathOwner
from toad.widgets.transcript_lines import Lines


class ReferenceRendering(CoreEventReceiver):
    """Borrow the source's observation for exactly this rendering lifetime."""
    def _on_mount(self):
        owner = ProjectPathOwner.containing(self)
        self.observe_core(self.app.coordination_access.events)
        self.observe_core(owner.link_context_events)
        self.app.coordination_access.show_references(self, owner.reference_context.requires_observation)

    def _on_unmount(self):
        # Textual dispatches each class's handler, including CoreEventReceiver's.
        self.app.coordination_access.show_references(self, False)

    @handles(LinkContextChanged)
    def reference_context_changed(self, event: LinkContextChanged):
        owner = ProjectPathOwner.containing(self)
        self.app.coordination_access.show_references(self, owner.reference_context.requires_observation)
        self.invalidate_lines()

    @abstractmethod
    def invalidate_lines(self, change=None): ...


class OpensLinks(CoreEventReceiver, MroDispatch):
    """A widget whose drawn links open what they name: one handler per kind of link."""

    def action_open(self, link: LineLink) -> None:
        """What a click on a drawn link runs (`LineLink.click`); the keyboard calls it too."""
        self.dispatch_sync(link)

    @handles(OpenTarget)
    def open_target(self, link: OpenTarget) -> None:
        self.publish_core(SelectTarget(NavigationTarget.named(link.target)))

    @handles(OpenHistoricalTarget)
    def open_historical_target(self, link: OpenHistoricalTarget) -> None:
        self.publish_core(SelectHistoricalIdentity(link.target, link.source))

    @handles(OpenReference)
    def open_reference(self, link: OpenReference) -> None:
        source = self.app.coordination_access.reference_context(link.reference.root)
        if not link.reference.current_in(source):
            self.notify(source.description or "This reference belongs to a replaced source.", severity="warning")
            return
        self.dispatch_sync(link.reference)

    @handles(ThreadDisplayReference, ChannelDisplayReference)
    def open_current_reference(self, reference) -> None:
        self.open_target(OpenTarget(reference.name))

    @handles(HistoricalDisplayReference)
    def open_recorded_reference(self, reference) -> None:
        self.open_historical_target(OpenHistoricalTarget(reference.name, reference.source))

    @handles(ProjectLink)
    def open_project_link(self, link: ProjectLink) -> None:
        self.run_worker(link.preview(self), group="open-link")

    def action_link(self, href: str) -> None:
        """Decode Markdown's transport once, then use the ordinary typed actions."""
        self.action_open(LineLink.from_href(href))


class OpensMessageNames(OpensLinks):
    """A block the cursor rests on while it draws a bus message: what the message's menu (`MessageRow.menu`) runs."""

    # The message under the cursor.
    message_row: MessageRow

    def action_open_sender(self) -> None:
        self.action_open(self.message_row.sender)

    def action_open_destination(self) -> None:
        self.action_open(self.message_row.destination)


class MessageRowBlock(OpensMessageNames):
    """A widget that is one bus message under the cursor: it offers the message's menu."""

    def get_block_menu(self) -> tuple[MenuItem, ...]:
        return self.message_row.menu


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


class LinkedRows(OpensLinks):
    """Draw prepared rows on the native background, using their entry's arrival fade."""

    arrival: AnimationEffects = AnimationEffects()

    def on_mount(self) -> None:
        self.arrival = next((entry for entry in cast(Widget, self).ancestors_with_self
                             if isinstance(entry, ConversationEntry)), LinkedRows.arrival)

    @property
    def line_sets(self) -> tuple[Lines, ...]:
        raise NotImplementedError

    def get_selection(self, selection: Selection) -> tuple[str, str] | None:
        rows = "\n".join("".join(segment.text for segment in row).rstrip()
                         for lines in self.line_sets for row in lines)
        return selection.extract(rows), "\n"

    def on_background(self, strip: Strip, paint: PaintState, y: int, x: int = 0) -> Strip:
        """Apply this entry's arrival fade and the widget's current background."""
        strip = self.arrival.paint_effects(strip)
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
