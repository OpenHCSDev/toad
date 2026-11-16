"""Where Textual placed a history's widgets: the rows read-ahead and reveals measure."""

from abc import abstractmethod
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from textual.geometry import Region
from textual.widget import Widget

from toad.client.history_pager import OffScreenRunway, PagingWindow, Runway


def protected_presentations(items: Iterable[Widget], endpoints: Iterable[Widget]) -> set[Widget]:
    """Resolve native selection/focus to its owning presentation, without geometry."""
    candidates = set(items)
    protected = set()
    for endpoint in endpoints:
        node = endpoint
        while isinstance(node, Widget):
            if node in candidates:
                protected.add(node)
                break
            node = node.parent
    return protected


class Unplaced:
    """A widget Textual's map has no entry for: the screen does not show it."""

    @staticmethod
    def found[Entry](entry: Entry | None, region: Callable[[Entry], Region]) -> Unplaced:
        """The one decoder of a Textual compositor map's entry: none means the screen does not show it."""
        return UNPLACED if entry is None else Placed(region(entry))

    def shown_rows(self, rows: range) -> Unplaced:
        """Where the screen shows some of the widget's rows: nowhere."""
        return self

    def top(self, default: int) -> int:
        """The screen row the widget starts at, or `default` when it is not shown."""
        return default

    def rows_within(self, origin: int, height: int) -> range:
        """The rows of a strip starting at screen row `origin` that the widget covers."""
        return range(0)

    def reveal_clicked(self, window: PagingWindow) -> None:
        """A click cannot land on a widget the screen does not show."""

    def shows_from(self, row: int, top: int) -> bool:
        """Whether the widget's `row` is drawn at or below screen row `top`."""
        return False

    def head_hidden(self, row: int, window: PagingWindow, height: int) -> bool:
        """Whether a message of this height starting at the widget's `row` needs its head placed.
        Where an unshown row is is unknown, so only the height decides."""
        return window.message_too_tall(height)

    def under[Found](self, rows: PointerRows[Found], y: int) -> Found:
        """What the widget draws at screen row `y`."""
        return rows.unshown()

    def runway(self, viewport: Unplaced) -> OffScreenRunway:
        """This widget's rows above and below `viewport`."""
        return OffScreenRunway()

    def runway_of(self, region: Region) -> OffScreenRunway:
        """As the viewport: the rows of a widget at `region` above and below it."""
        return OffScreenRunway()

    def overlaps(self, region: Region) -> bool:
        return False

    def shows(self, region: Region, clip: Region) -> bool:
        """As the viewport: whether a widget at `region`, clipped to `clip`, is in view."""
        return False

    def regions(self) -> tuple[Region, ...]:
        """The screen regions the widget is shown in."""
        return ()


UNPLACED = Unplaced()


@dataclass(frozen=True)
class Placed(Unplaced):
    """Where the screen shows the widget, including the part scrolled out of view."""

    region: Region

    def regions(self) -> tuple[Region, ...]:
        return (self.region,)

    def shown_rows(self, rows: range) -> Placed:
        region = self.region
        return Placed(Region(region.x, region.y + rows.start, region.width, len(rows)))

    def top(self, default: int) -> int:
        return self.region.y

    def rows_within(self, origin: int, height: int) -> range:
        return range(max(0, self.region.y - origin), min(height, self.region.bottom - origin))

    def reveal_clicked(self, window: PagingWindow) -> None:
        """Scroll a clicked message whose head is above the viewport to its head."""
        region = self.region
        if window.message_head_hidden(region.height, region.y):
            window.release_anchor()
            window.scroll_relative(
                y=region.y - window.scrollable_content_region.y,
                animate=False, immediate=True,
            )

    def shows_from(self, row: int, top: int) -> bool:
        return self.region.y + row >= top

    def head_hidden(self, row: int, window: PagingWindow, height: int) -> bool:
        return window.message_head_hidden(height, self.region.y + row)

    def under[Found](self, rows: PointerRows[Found], y: int) -> Found:
        return rows.shown_row(y - self.region.y)

    def runway(self, viewport: Unplaced) -> OffScreenRunway:
        return viewport.runway_of(self.region)

    def runway_of(self, region: Region) -> OffScreenRunway:
        frame = self.region
        return Runway(frame.y - region.y, region.bottom - frame.bottom) if region.overlaps(frame) else OffScreenRunway()

    def overlaps(self, region: Region) -> bool:
        return region.overlaps(self.region)

    def shows(self, region: Region, clip: Region) -> bool:
        viewport = self.region
        return region.overlaps(viewport) and region.overlaps(clip) and clip.overlaps(viewport)


class PointerRows[Found]:
    """A widget that answers what it draws at one of its rows, or that it is not shown.
    A mixin beside Widget, so it declares its methods without ABC's metaclass."""

    @abstractmethod
    def shown_row(self, row: int) -> Found: ...

    @abstractmethod
    def unshown(self) -> Found: ...


def arranged(widget: Widget) -> Unplaced:
    """Where the screen's arranged map shows a widget: the one read of that Textual map."""
    return Unplaced.found(widget.screen._compositor.visible_widgets.get(widget), lambda geometry: geometry[0])
