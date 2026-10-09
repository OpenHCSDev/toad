from __future__ import annotations

from abc import ABC, ABCMeta, abstractmethod
from dataclasses import dataclass
from inspect import getattr_static
from typing import TYPE_CHECKING, ClassVar, Iterable, NamedTuple

from textual._spatial_map import SpatialMap
from textual._measurement import (
    NATIVE_LAYOUT_HEIGHT, NATIVE_OPTIMAL_WIDTH,
    HeightDependency, height_dependency,
)
from textual.canvas import Canvas, Rectangle
from textual.geometry import Offset, Region, Size, Spacing
from textual.strip import StripRenderable

if TYPE_CHECKING:
    from typing_extensions import TypeAlias

    from textual.widget import Widget

ArrangeResult: TypeAlias = "list[WidgetPlacement]"


@dataclass
class DockArrangeResult:
    """Result of [Layout.arrange][textual.layout.Layout.arrange]."""

    placements: list[tuple[int, WidgetPlacement]]
    """Original first-widget ordinals and their placements, in source order."""
    widgets: set[Widget]
    """A set of widgets in the arrangement."""
    scroll_spacing: Spacing
    """Spacing to reduce scrollable area."""

    _spatial_map: SpatialMap[tuple[int, WidgetPlacement]] | None = None
    """A Spatial map to query widget placements."""

    @classmethod
    def from_placements(
        cls, placements: list[WidgetPlacement], widgets: set[Widget], scroll_spacing: Spacing,
    ) -> DockArrangeResult:
        """Bind rank once when the original arrangement is constructed.

        Duplicate placements for one widget share its first source ordinal.
        Only this indexed sequence survives; the construction dictionary and
        layout producer's unindexed list are not companion retained resources.
        """
        ordinals: dict[Widget, int] = {}
        return cls(
            [(ordinals.setdefault(placement.widget, index), placement)
             for index, placement in enumerate(placements)],
            widgets, scroll_spacing,
        )

    @property
    def spatial_map(self) -> SpatialMap[tuple[int, WidgetPlacement]]:
        """A lazy-calculated spatial map."""
        if self._spatial_map is None:
            self._spatial_map = SpatialMap()
            self._spatial_map.insert(
                (
                    placement.region.grow(placement.margin),
                    placement.offset,
                    placement.fixed,
                    placement.overlay,
                    (ordinal, placement),
                )
                for ordinal, placement in self.placements
            )

        return self._spatial_map

    @property
    def total_region(self) -> Region:
        """The total area occupied by the arrangement.

        Returns:
            A Region.
        """
        _top, right, bottom, _left = self.scroll_spacing
        return self.spatial_map.total_region.grow((0, right, bottom, 0))

    def get_visible_placements(
        self, region: Region, *, retain: Iterable[Widget] = (),
    ) -> list[tuple[int, WidgetPlacement]]:
        """Admit original indexed placements for visible and retained widgets.

        Args:
            region: A region.
            retain: Original geometry targets which also need an offscreen box.

        Returns:
            Original ordinals and placements, preserving spatial query ordering.
        """
        if self.total_region in region:
            # Short circuit for when we want all the placements
            return self.placements
        visible_placements = self.spatial_map.get_values_in_region(region)
        overlaps = region.overlaps
        culled_placements = [
            (ordinal, placement)
            for ordinal, placement in visible_placements
            if placement.fixed or overlaps(placement.region + placement.offset)
        ]
        retained_widgets = self.widgets.intersection(retain)
        if retained_widgets:
            visible_widgets = {placement.widget for _, placement in culled_placements}
            if retained_widgets - visible_widgets:
                return [
                    (ordinal, placement)
                    for ordinal, placement in self.placements
                    if placement.widget in visible_widgets or placement.widget in retained_widgets
                ]
        return culled_placements


class WidgetPlacement(NamedTuple):
    """The position, size, and relative order of a widget within its parent."""

    region: Region
    offset: Offset
    margin: Spacing
    widget: Widget
    order: int = 0
    fixed: bool = False
    overlay: bool = False
    absolute: bool = False

    @classmethod
    def process_offsets(cls, placements, bounds: Region, offset: Offset):
        """Acquire each original constraint before descendant placement begins."""
        return [(ordinal, placement.process_offset(bounds, offset))
                for ordinal, placement in placements]

    @property
    def reset_origin(self) -> WidgetPlacement:
        """Reset the origin in the placement (moves it to (0, 0))."""
        return self._replace(region=self.region.reset_offset)

    @classmethod
    def translate(
        cls, placements: list[WidgetPlacement], translate_offset: Offset
    ) -> list[WidgetPlacement]:
        """Move all non-absolute placements by a given offset.

        Args:
            placements: List of placements.
            offset: Offset to add to placements.

        Returns:
            Placements with adjusted region, or same instance if offset is null.
        """
        if translate_offset:
            return [
                cls(
                    (
                        region + translate_offset
                        if layout_widget.absolute_offset is None
                        else region
                    ),
                    offset,
                    margin,
                    layout_widget,
                    order,
                    fixed,
                    overlay,
                    absolute,
                )
                for region, offset, margin, layout_widget, order, fixed, overlay, absolute in placements
            ]
        return placements

    @classmethod
    def apply_absolute(cls, placements: list[WidgetPlacement]) -> None:
        """Applies absolute offsets (in place).

        Args:
            placements: A list of placements.
        """
        for index, placement in enumerate(placements):
            if placement.absolute:
                placements[index] = placement.reset_origin

    @classmethod
    def get_bounds(cls, placements: Iterable[WidgetPlacement]) -> Region:
        """Get a bounding region around all placements.

        Args:
            placements: A number of placements.

        Returns:
            An optimal binding box around all placements.
        """
        bounding_region = Region.from_union(
            [placement.region.grow(placement.margin) for placement in placements]
        )
        return bounding_region

    def process_offset(
        self, constrain_region: Region, absolute_offset: Offset
    ) -> WidgetPlacement:
        """Apply any absolute offset or constrain rules to the placement.

        Args:
            constrain_region: The container region when applying constrain rules.
            absolute_offset: Default absolute offset that moves widget into screen coordinates.

        Returns:
            Processes placement, may be the same instance.
        """
        widget = self.widget
        styles = widget.styles
        if not widget.uses_screen_coordinates:
            # Bail early if there is nothing to do
            return self
        region = self.region
        margin = self.margin
        if widget.absolute_offset is not None:
            region = region.at_offset(
                widget.absolute_offset + margin.top_left - absolute_offset
            )

        region = region.translate(self.offset).constrain(
            styles.constrain_x,
            styles.constrain_y,
            self.margin,
            constrain_region - absolute_offset,
        )

        offset = region.offset - self.region.offset
        if offset != self.offset:
            region, _offset, margin, widget, order, fixed, overlay, absolute = self
            placement = WidgetPlacement(
                region, offset, margin, widget, order, fixed, overlay, absolute
            )
            return placement
        return self


class _LayoutMeta(ABCMeta):
    """Keep Layout's declaration supply current when its namespace changes."""

    def __new__(mcls, name, bases, namespace, **kwargs):
        declaration = super().__new__(mcls, name, bases, namespace, **kwargs)
        if any(isinstance(base, _LayoutMeta) for base in bases):
            Layout._publish_document_implementation.__func__(declaration)
        return declaration

    def __setattr__(cls, name, value):
        super().__setattr__(name, value)
        _LayoutMeta._document_declaration_changed(cls, name)

    def __delattr__(cls, name):
        super().__delattr__(name)
        _LayoutMeta._document_declaration_changed(cls, name)

    def _document_declaration_changed(cls, name):
        if name not in cls._document_method_names and name not in (
            "_document_methods", "__bases__",
        ):
            return
        # Use Python's actual descendant declarations, not a second catalog.
        pending = [cls]
        visited = set()
        while pending:
            declaration = pending.pop()
            if declaration in visited:
                continue
            visited.add(declaration)
            Layout._publish_document_implementation.__func__(declaration)
            pending.extend(type.__subclasses__(declaration))


class Layout(ABC, metaclass=_LayoutMeta):
    """Base class of the object responsible for arranging Widgets within a container."""

    name: ClassVar[str] = ""
    _content_width_dependency: ClassVar[HeightDependency]
    _content_height_dependency: ClassVar[HeightDependency]
    _arrangement_height_dependency: ClassVar[HeightDependency]
    _document_method_names = (
        "arrange", "get_content_width", "get_content_height", "__init__",
        "clear_cache", "render_keyline", "_document_inputs",
    )
    _document_instance_method_names = frozenset(
        name for name in _document_method_names if name != "__init__"
    )
    _document_methods: ClassVar[tuple | None] = None
    _document_implementation: ClassVar[tuple | None] = None

    def __init_subclass__(cls, **kwargs) -> None:
        from textual._measurement import CONTEXT_HEIGHT

        super().__init_subclass__(**kwargs)
        cls._content_width_dependency = getattr(cls.get_content_width, "_height_dependency", CONTEXT_HEIGHT)
        cls._content_height_dependency = getattr(cls.get_content_height, "_height_dependency", CONTEXT_HEIGHT)
        cls._arrangement_height_dependency = getattr(cls.arrange, "_height_dependency", CONTEXT_HEIGHT)
        if ("arrange" in cls.__dict__ and "get_content_height" not in cls.__dict__
                and cls._arrangement_height_dependency is CONTEXT_HEIGHT):
            cls._content_height_dependency = CONTEXT_HEIGHT
        if ("arrange" in cls.__dict__ and "get_content_width" not in cls.__dict__
                and cls._arrangement_height_dependency is CONTEXT_HEIGHT):
            cls._content_width_dependency = CONTEXT_HEIGHT

    @classmethod
    def _publish_document_implementation(cls):
        """Admit actual C3 supply at declaration or namespace publication.

        Foreign mixins can mutate without entering this class owner. They need
        an explicit detached contract; inherited native admission cannot
        certify those independently changing declarations.
        """
        expected = cls._document_methods
        unmanaged = (
            type(cls).__setattr__ is not _LayoutMeta.__setattr__
            or type(cls).__delattr__ is not _LayoutMeta.__delattr__
            or type(cls).__getattribute__ is not type.__getattribute__
            or any(
                base not in Layout.__mro__ and not issubclass(base, Layout)
                for base in cls.__mro__[1:]
            )
        )
        actual = (
            None if expected is None or unmanaged else
            tuple(getattr_static(cls, name) for name in cls._document_method_names)
        )
        supply = (cls, *actual) if actual is not None and actual == expected else None
        type.__setattr__(cls, "_document_implementation", supply)

    def clear_cache(self) -> None:
        """Release layout-owned derived state after structural child removal."""

    def document_key(self) -> tuple:
        """Immutable inputs for detached use; custom layouts supply this contract."""
        implementation = type(self)._document_implementation
        if implementation is None or implementation[0] is not type(self):
            raise TypeError(f"{type(self).__name__} must declare its detached layout inputs")
        # Instance dispatch changes binding even when the assigned object is
        # the same unbound function. Constructor dispatch belongs to the type.
        if not self.__dict__.keys().isdisjoint(type(self)._document_instance_method_names):
            raise TypeError(f"{type(self).__name__} has instance-specific layout dispatch")
        return (*implementation, tuple(self._document_inputs().items()))

    def _document_inputs(self) -> dict:
        return {}

    def acquire_document(self) -> Layout:
        """Acquire algorithm/configuration with independent derived geometry.

        Custom layouts own this construction contract. A scene layout's cached
        placements and child custody are not document inputs.
        """
        self.document_key()
        return type(self)(**self._document_inputs())

    def __repr__(self) -> str:
        return f"<{self.name}>"

    @abstractmethod
    def arrange(
        self,
        parent: Widget,
        children: list[Widget],
        size: Size,
        greedy: bool = True,
    ) -> ArrangeResult:
        """Generate a layout map that defines where on the screen the widgets will be drawn.

        Args:
            parent: Parent widget.
            size: Size of container.

        Returns:
            An iterable of widget location
        """

    @height_dependency(NATIVE_OPTIMAL_WIDTH)
    def get_content_width(self, widget: Widget, container: Size, viewport: Size) -> int:
        """Get the optimal content width by arranging children.

        Args:
            widget: The container widget.
            container: The container size.
            viewport: The viewport size.

        Returns:
            Width of the content.
        """
        if not widget._nodes:
            width = 0
        else:
            arrangement = widget.arrange(
                Size(0 if widget.shrink else container.width, 0),
                optimal=True,
            )
            width = arrangement.total_region.right
        return width

    @height_dependency(NATIVE_LAYOUT_HEIGHT)
    def get_content_height(
        self, widget: Widget, container: Size, viewport: Size, width: int
    ) -> int:
        """Get the content height.

        Args:
            widget: The container widget.
            container: The container size.
            viewport: The viewport.
            width: The content width.

        Returns:
            Content height (in lines).
        """
        if widget._nodes:
            if not widget.styles.is_docked and all(
                child.styles.is_dynamic_height for child in widget.displayed_children
            ):
                # An exception for containers with all dynamic height widgets
                arrangement = widget.arrange(Size(width, container.height))
            else:
                arrangement = widget.arrange(Size(width, 0))
            height = arrangement.total_region.height
        else:
            height = 0
        return height

    def render_keyline(self, container: Widget) -> StripRenderable:
        """Render keylines around all widgets.

        Args:
            container: The container widget.

        Returns:
            A renderable to draw the keylines.
        """
        # Keylines and their child rectangles belong to the same geometry.
        # A complete subtree capture admits offscreen boxes before those
        # widgets receive resize notifications; outer_size is that older value.
        width, height = container.region.size
        canvas = Canvas(width, height)

        line_style, keyline_color = container.styles.keyline
        if keyline_color:
            keyline_color = container.background_colors[0] + keyline_color

        container_offset = container.content_region.offset

        def get_rectangle(region: Region) -> Rectangle:
            """Get a canvas Rectangle that wraps a region.

            Args:
                region: Widget region.

            Returns:
                A Rectangle that encloses the widget.
            """
            offset = region.offset - container_offset - (1, 1)
            width, height = region.size
            return Rectangle(offset, width + 2, height + 2, keyline_color, line_style)

        primitives = [
            get_rectangle(widget.region)
            for widget in container.children
            if widget.visible
        ]
        canvas_renderable = canvas.render(primitives, container.rich_style)
        return canvas_renderable
