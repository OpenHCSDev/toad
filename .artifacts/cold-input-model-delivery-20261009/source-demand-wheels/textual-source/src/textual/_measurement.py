"""Declaration-owned available-height dependencies for native layout reuse."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Callable, TypeVar

from textual.css.scalar import Scalar, Unit
from textual.css.styles import RenderStyles
from textual.geometry import Spacing

if TYPE_CHECKING:
    from textual.widget import Widget


class HeightDependency(ABC):
    @abstractmethod
    def depends(self, widget: Widget, *, greedy: bool = True) -> bool:
        """Whether incoming height changes this operation in its actual box mode.

        Placement propagates greedy mode. Content measurements select the mode
        used by their own algorithm, independent of the outer box operation.
        """

    def box_depends(self, widget: Widget, *, greedy: bool = True) -> bool:
        return self.depends(widget, greedy=greedy) or widget._has_relative_children_height

    def styles_sensitive(self, widget: Widget) -> bool:
        """Unknown measurements may read any rule, not just native box inputs.

        Available-height independence alone makes no claim about style inputs.
        Native algorithms below supply their narrower source relationship.
        """
        return True


class ContextHeight(HeightDependency):
    def depends(self, widget: Widget, *, greedy: bool = True) -> bool:
        return True


class IndependentHeight(HeightDependency):
    def depends(self, widget: Widget, *, greedy: bool = True) -> bool:
        return False


class NativeContainerSelection(IndependentHeight):
    """Native selection reads child membership / layout, not paint rules.

    User-declared independent getters retain IndependentHeight's conservative
    style contract; height independence alone says nothing about paint inputs.
    """

    def styles_sensitive(self, widget: Widget) -> bool:
        return False


class StoredVirtualSize(HeightDependency):
    """The original line surface measures its authored reactive extent.

    Extent writes already invalidate through Reactive(layout=True). Computed
    or replaced descriptors retain arbitrary style/container dependencies.
    """

    def depends(self, widget: Widget, *, greedy: bool = True) -> bool:
        from textual.reactive import _STORED_REACTIVE_ACCESS
        from textual.widget import Widget

        return (
            type(widget).virtual_size is not Widget.virtual_size
            or widget._reactive_accessors.get("virtual_size") is not _STORED_REACTIVE_ACCESS
        )

    styles_sensitive = depends


class NativeWidgetMeasurementHeight(HeightDependency):
    @abstractmethod
    def layout_dependency(self, widget: Widget) -> HeightDependency:
        """The native layout owns the selected measurement's dependency."""

    def depends(self, widget: Widget, *, greedy: bool = True) -> bool:
        if widget._container_selection_dependency.depends(widget):
            return True
        if not widget.is_container:
            # Native leaf visuals receive rules and width, not container height.
            return False
        if not widget._native_measurement_layout_hooks:
            return True
        # Native get_content_height / get_content_width choose their own
        # arrangement inputs; outer optimal placement cannot change those.
        return self.layout_dependency(widget).depends(widget)

    def box_depends(self, widget: Widget, *, greedy: bool = True) -> bool:
        if widget._container_selection_dependency.depends(widget):
            return True
        if not widget.is_container:
            return False
        if not widget._native_measurement_layout_hooks:
            return True
        return self.layout_dependency(widget).box_depends(widget)

    def styles_sensitive(self, widget: Widget) -> bool:
        if widget._container_selection_dependency.styles_sensitive(widget):
            return True
        if not widget.is_container:
            return widget._render_styles_sensitive()
        if not widget._native_measurement_layout_hooks:
            return True
        return self.layout_dependency(widget).styles_sensitive(widget)


class NativeWidgetHeight(NativeWidgetMeasurementHeight):
    def layout_dependency(self, widget: Widget) -> HeightDependency:
        return widget.layout._content_height_dependency


class NativeWidgetWidth(NativeWidgetMeasurementHeight):
    def layout_dependency(self, widget: Widget) -> HeightDependency:
        return widget.layout._content_width_dependency


class NativeLayoutHeight(HeightDependency):
    def depends(self, widget: Widget, *, greedy: bool = True) -> bool:
        # Conservatively require a declaration for the arranger too. Even the
        # fixed-zero branch need not opt unknown/custom layout hooks into reuse.
        return widget._arrangement_depends_on_available_height()

    def box_depends(self, widget: Widget, *, greedy: bool = True) -> bool:
        if _arrangement_wrapper_uses_height(widget):
            return True
        return widget.layout._arrangement_height_dependency.box_depends(widget, greedy=True)

    def styles_sensitive(self, widget: Widget) -> bool:
        if not widget._native_measurement_layout_hooks:
            return True
        return widget.layout._arrangement_height_dependency.styles_sensitive(widget)


class NativeOptimalWidth(IndependentHeight):
    """Native width arranges at zero height but reads arrangement styles."""

    def styles_sensitive(self, widget: Widget) -> bool:
        return NATIVE_LAYOUT_HEIGHT.styles_sensitive(widget)


class FlowHeight(HeightDependency):
    def styles_sensitive(self, widget: Widget) -> bool:
        # Native placement consumes declared geometry rules and child boxes.
        # Original rule publication owns descendant measurement invalidation;
        # querying native ancestors must not walk those children again.
        from textual.widget import Widget

        # A custom hook can be independent of incoming height while reading
        # paint rules. Only the original native no-op hooks narrow this fact.
        return (
            type(widget).arrange is not Widget.arrange
            or type(widget).pre_layout is not Widget.pre_layout
            or type(widget).process_layout is not Widget.process_layout
        )

    def depends(self, widget: Widget, *, greedy: bool = True) -> bool:
        styles = widget.styles
        if (not widget._native_measurement_layout_hooks
                or styles.align_horizontal != "left" or styles.align_vertical != "top"):
            return True
        for child in widget.displayed_children:
            child_styles = child.styles
            if child_styles.is_docked or child_styles.is_split or child_styles.overlay == "screen":
                return True
            # Match native auto-parent stretch semantics, which treat all
            # percentage heights as relative even for a raw width-axis scalar.
            if child_styles.is_relative_height:
                return True
            if child._box_depends_on_available_height(greedy=greedy):
                return True
        return False

    # Child box proofs already reject auto descendants with relative heights.
    # Rewalking that same subtree through _has_relative_children_height would
    # duplicate the dependency traversal we just completed.
    box_depends = depends


class StreamHeight(FlowHeight):
    # Stream/Grid share the native child-input relation, but keep the original
    # general box operation. Reuse its one implementation, not Flow's box proof.
    box_depends = HeightDependency.box_depends

    def depends(self, widget: Widget, *, greedy: bool = True) -> bool:
        # Stream measures content directly, even when a child's CSS box height
        # is fixed. A box proof alone cannot certify this operation.
        return any(child._content_height_dependency.depends(child)
                   for child in widget.displayed_children)


def _scalar_uses_height(scalar: Scalar, *, height_fraction: bool = False) -> bool:
    unit = scalar.percent_unit if scalar.unit is Unit.PERCENT else scalar.unit
    return (type(scalar).resolve is not Scalar.resolve or unit is Unit.HEIGHT
            or (height_fraction and unit is Unit.FRACTION))


class GridHeight(FlowHeight):
    box_depends = HeightDependency.box_depends

    def depends(self, widget: Widget, *, greedy: bool = True) -> bool:
        styles = widget.styles
        rows, columns = styles.grid_rows or (), styles.grid_columns or ()
        # Default rows become fractional at nonzero height for non-auto parents.
        if (not rows and not styles.is_auto_height
                or any(_scalar_uses_height(row, height_fraction=True) for row in rows)
                or any(_scalar_uses_height(column) for column in columns)):
            return True
        auto_rows = not rows or any(row.is_auto for row in rows)
        auto_columns = any(column.is_auto for column in columns)
        for child in widget.displayed_children:
            child_styles = child.styles
            # Auto cells pass the outer size directly to content measurement
            # and extrema. Final boxes/offsets receive the already-resolved cell
            # size, so fractional child boxes are safe once tracks are proven.
            # Only auto tracks ask for content or resolve extrema against the
            # incoming outer size. Fixed/fractional columns and fixed rows
            # resolve their cell sizes first; final child boxes read those cell
            # sizes, not the outer height. An unused custom measurement must
            # not make measurement and placement arrange the same grid twice.
            if auto_rows and child_styles.row_span == 1:
                if child._content_height_dependency.depends(child):
                    return True
                if any(scalar is not None and _scalar_uses_height(scalar) for scalar in (
                    child_styles.min_height, child_styles.max_height,
                )):
                    return True
            if auto_columns and child_styles.column_span == 1:
                if child._content_width_dependency.depends(child):
                    return True
                if any(scalar is not None and _scalar_uses_height(scalar) for scalar in (
                    child_styles.min_width, child_styles.max_width,
                )):
                    return True
        return False


CONTEXT_HEIGHT = ContextHeight()
INDEPENDENT_HEIGHT = IndependentHeight()
NATIVE_CONTAINER_SELECTION = NativeContainerSelection()
STORED_VIRTUAL_SIZE = StoredVirtualSize()
NATIVE_WIDGET_HEIGHT = NativeWidgetHeight()
NATIVE_WIDGET_WIDTH = NativeWidgetWidth()
NATIVE_LAYOUT_HEIGHT = NativeLayoutHeight()
NATIVE_OPTIMAL_WIDTH = NativeOptimalWidth()
FLOW_HEIGHT = FlowHeight()
STREAM_HEIGHT = StreamHeight()
GRID_HEIGHT = GridHeight()

Function = TypeVar("Function", bound=Callable)


def height_dependency(policy: HeightDependency) -> Callable[[Function], Function]:
    """Declare a method's dependency; unknown overrides remain context-dependent.

    This does not cache a method's result or retain a widget. A declaration must
    describe the whole implementation, including additional work around super().
    A declared is_container getter must also publish changes to its selection
    inputs through the original layout invalidation (refresh(layout=True),
    layout reactives, or native child/style publication). Independence from
    incoming height does not make independently changing selection immutable.
    """
    def decorate(function: Function) -> Function:
        function._height_dependency = policy  # type: ignore[attr-defined]
        return function
    return decorate


def _local_box_inputs(widget: Widget) -> tuple[bool, bool, bool, bool, bool]:
    """Resolve local scalar dependencies once per owning style generation."""
    styles = widget.styles
    if type(styles) is not RenderStyles:
        return True, False, False, False, False
    # Retain the actual source so replacement cannot reuse an unrelated epoch.
    revision = id(styles), styles, styles._cache_key
    cached = widget.__dict__.get("_box_style_dependency_cache")
    if cached is not None and cached[0] == revision:
        return cached[1]
    width, height = styles.width, styles.height
    min_width, max_width = styles.min_width, styles.max_width
    min_height, max_height = styles.min_height, styles.max_height
    for scalar in (width, height, min_width, max_width, min_height, max_height):
        if scalar is not None:
            # Compile this check at the style-plan boundary, not each cache hit.
            # A custom scalar resolver need not obey its nominal unit's inputs.
            if type(scalar).resolve is not Scalar.resolve:
                result = (True, False, False, False, False)
                break
            unit = scalar.percent_unit if scalar.unit is Unit.PERCENT else scalar.unit
            if unit is Unit.HEIGHT:
                result = (True, False, False, False, False)
                break
    else:
        styles_only = (
            all(scalar is None or type(scalar) is Scalar for scalar in (
                width, height, min_width, max_width, min_height, max_height,
            ))
            and (width is None or not width.is_auto)
            and (height is None or not height.is_auto)
            and all(type(spacing) is Spacing and all(
                type(cell) in (int, bool) for cell in spacing
            ) for spacing in (styles.margin, styles.padding))
            and all(type(edge) is tuple and type(edge[0]) is str
                    for edge in styles.border)
        )
        independent_width = (
            styles_only
            and width is not None
            # Fill, percentages and fractions still read available width.
            and all(scalar is None or (
                (scalar.percent_unit if scalar.unit is Unit.PERCENT else scalar.unit)
                not in (Unit.WIDTH, Unit.FRACTION)
            ) for scalar in (width, height, min_width, max_width, min_height, max_height))
            # Non-cell max widths have a zero-width auto-parent exception.
            and (max_width is None or max_width.is_cells)
        )
        result = (
            height is None or height.is_fraction
            or (min_height is not None and min_height.is_fraction)
            # Non-cell max heights have a zero-height auto-parent exception.
            or (max_height is not None and not max_height.is_cells),
            width is not None and (width.is_auto or width.is_fraction),
            height is not None and height.is_auto,
            styles_only,
            independent_width,
        )
    widget._box_style_dependency_cache = revision, result
    return result


def box_depends_on_available_height(widget: Widget, *, greedy: bool) -> bool:
    """Conservative proof for the native box resolver, including its extrema."""
    if (not widget._native_box_measurement
            or widget._container_selection_dependency.depends(widget)):
        return True
    depends, content_width, content_height, _, _ = _local_box_inputs(widget)
    if depends:
        return True
    # Fractional width becomes auto only in optimal sizing. Normal placement
    # resolves the supplied fraction without calling get_content_width.
    if (content_width and (not greedy or widget.styles.width.is_auto)
            and widget._content_width_dependency.depends(widget)):
        return True
    if content_height:
        return widget._content_height_dependency.box_depends(widget)
    return False


def _arrangement_wrapper_uses_height(widget: Widget) -> bool:
    styles = widget.styles
    if (not widget._native_measurement_layout_hooks
            or styles.align_horizontal != "left" or styles.align_vertical != "top"):
        return True
    return any(child.styles.is_docked or child.styles.is_split
               or child.styles.overlay == "screen" for child in widget.displayed_children)
