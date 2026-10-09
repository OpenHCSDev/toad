from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from textual.geometry import Region, Size, Spacing

if TYPE_CHECKING:
    from textual.dom import DOMNode
    from textual.widget import Widget


class MapGeometry(NamedTuple):
    """Defines the absolute location of a Widget."""

    region: Region
    """The (screen) [region][textual.geometry.Region] occupied by the widget."""
    order: tuple[tuple[int, int, int], ...]
    """Tuple of tuples defining the painting order of the widget.

    Each successive triple represents painting order information with regards to
    ancestors in the DOM hierarchy and the last triple provides painting order
    information for this specific widget.
    """
    clip: Region
    """A [region][textual.geometry.Region] to clip the widget by (if a Widget is within a container)."""
    virtual_size: Size
    """The virtual [size][textual.geometry.Size] (scrollable area) of a widget if it is a container."""
    container_size: Size
    """The container [size][textual.geometry.Size] (area not occupied by scrollbars)."""
    virtual_region: Region
    """The [region][textual.geometry.Region] relative to the container (but not necessarily visible)."""
    dock_gutter: Spacing
    """Space from the container reserved by docked widgets."""
    ancestors: tuple[DOMNode, ...]
    """Acquired native owner ancestry, nearest first, independent of later DOM writes."""
    gutter: Spacing
    """The actual content inset acquired with this placement, not current styles."""

    @property
    def content_region(self) -> Region:
        """Content coordinates from the same original placement and style input."""
        return self.region.shrink(self.gutter)

    @classmethod
    def from_widget(cls, widget: Widget, region: Region, order: tuple,
                    clip: Region, virtual_size: Size, container_size: Size,
                    virtual_region: Region, dock_gutter: Spacing) -> MapGeometry:
        """Acquire content inset and ancestry at the original placement producer."""
        return cls(region, order, clip, virtual_size, container_size,
                   virtual_region, dock_gutter, tuple(widget.walk_ancestors()), widget.gutter)

    def with_ancestors(self, widget: Widget, root: Widget,
                       ancestors: tuple[DOMNode, ...]) -> MapGeometry:
        """Rebind only the outside of an original subtree placement.

        Borrowed descendants retain their acquired internal parent path. The
        containing arrangement supplies the root's actual external ancestry.
        """
        if widget is root:
            acquired = ancestors
        elif root in self.ancestors:
            acquired = self.ancestors[:self.ancestors.index(root) + 1] + ancestors
        else:
            return self
        return self if acquired == self.ancestors else self._replace(ancestors=acquired)

    @property
    def visible_region(self) -> Region:
        """The Widget region after clipping."""
        return self.clip.intersection(self.region)
