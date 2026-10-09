from __future__ import annotations

from operator import attrgetter
from typing import TYPE_CHECKING, Iterable, Iterator, NamedTuple

from textual.geometry import NULL_REGION, Offset, Region, Shape

if TYPE_CHECKING:
    from textual.widget import Widget


class Selection(NamedTuple):
    """A selected range of lines."""

    start: Offset | None
    """Offset or None for `start`."""
    end: Offset | None
    """Offset or None for `end`."""

    @classmethod
    def from_offsets(cls, offset1: Offset, offset2: Offset) -> Selection:
        """Create selection from 2 offsets.

        Args:
            offset1: First offset.
            offset2: Second offset.

        Returns:
            New Selection.
        """
        offsets = sorted([offset1, offset2], key=(lambda offset: (offset.y, offset.x)))
        return cls(*offsets)

    def extract(self, text: str) -> str:
        """Extract selection from text.

        Args:
            text: Raw text pulled from widget.

        Returns:
            Extracted text.
        """
        lines = text.splitlines()
        if not lines:
            return ""
        if self.start is None:
            start_line_index = 0
            start_offset = 0
        else:
            start_line_index, start_offset = self.start.transpose

        if self.end is None:
            end_line = len(lines)
            end_offset = len(lines[-1])
        else:
            end_line, end_offset = self.end.transpose
        end_line = min(len(lines), end_line)

        if start_line_index == end_line:
            return lines[start_line_index][start_offset:end_offset]

        selection: list[str] = []
        selected_lines = lines[start_line_index : end_line + 1]
        if len(selected_lines) >= 2:
            first_line, *mid_lines, last_line = selected_lines
            selection.append(first_line[start_offset:])
            selection.extend(mid_lines)
            selection.append(last_line[:end_offset])
        else:
            try:
                selection.append(lines[start_line_index][start_offset:end_offset])
            except IndexError:
                pass
        return "\n".join(selection)

    def get_span(self, y: int) -> tuple[int, int] | None:
        """Get the selected span in a given line.

        Args:
            y: Offset of the line.

        Returns:
            A tuple of x start and end offset, or None for no selection.
        """
        start, end = self
        if start is None and end is None:
            # Selection covers everything
            return 0, -1

        if start is not None and end is not None:
            if y < start.y or y > end.y:
                # Outside
                return None
            if y == start.y and start.y == end.y:
                # Same line
                return start.x, end.x
            if y == end.y:
                # Last line
                return 0, end.x
            if y == start.y:
                return start.x, -1
            # Remaining lines
            return 0, -1

        if start is None and end is not None:
            if y == end.y:
                return 0, end.x
            if y > end.y:
                return None
            return 0, -1

        if end is None and start is not None:
            if y == start.y:
                return start.x, -1
            if y > start.y:
                return 0, -1
            return None
        return 0, -1


SELECT_ALL = Selection(None, None)


class SelectStart(NamedTuple):
    """Describes the start of a select."""

    container: Widget
    """The container under the cursor."""
    container_pointer_delta: Offset
    """The delta between the initial container offset and pointer."""
    container_initial_offset: Offset
    """The initial offset of the container."""
    container_initial_scroll_offset: Offset
    """The initial scroll offset of the container."""
    content_widget: Widget | None
    """The content widget under the pointer (if any)."""
    content_offset: Offset | None
    """The content offset of the widget under the pointer (if appropriate)."""

    @property
    def pointer_start_offset(self) -> Offset:
        """The pointer start offset adjusted for scroll."""
        return (
            self.container.region.offset
            + self.container_pointer_delta
            + (self.container.scroll_offset - self.container_initial_scroll_offset)
        )


class SelectEnd(NamedTuple):
    """The end of a select."""

    container: Widget
    """The container widget under the pointer."""
    content_widget: Widget | None
    """The content widget under the pointer (if any)."""
    content_offset: Offset | None
    """The content offset of the widget under the pointer."""


class SelectState(NamedTuple):
    """An object which describes the current select state."""

    screen_offset: Offset
    """The current mouse position, in screen space."""
    start: SelectStart
    """Describes the select start."""
    end: SelectEnd | None = None
    """Describes the select end."""

    def _walk_involved_widgets(self) -> Iterator[Widget]:
        """Original containers and content referenced by the pointer endpoints."""
        for endpoint in (self.start, self.end):
            if endpoint is not None:
                yield endpoint.container
                if endpoint.content_widget is not None:
                    yield endpoint.content_widget

    @property
    def is_attached_to_dom(self) -> bool:
        """Are the widgets involved attached to the DOM?"""
        return all(widget.is_attached for widget in self._walk_involved_widgets())

    def references_retired(self, widgets: set[Widget]) -> bool:
        """Whether removing these resources retires the pointer intent."""
        return any(widget in widgets for widget in self._walk_involved_widgets())

    def selections(self) -> dict[Widget, Selection]:
        """Project the completed pointer intent into original content ranges."""
        assert self.end is not None
        if self.is_single_content_widget:
            start_offset, end_offset = self.content_offsets
            assert self.start.content_widget is not None
            return {
                self.start.content_widget: Selection.from_offsets(
                    start_offset, end_offset + (1, 0)
                )
            }
        selections = {widget: SELECT_ALL for widget in self._walk_selected_widgets()}
        self._apply_content_selections(selections)
        return selections

    @property
    def is_single_content_widget(self) -> bool:
        """Does the start and end fall on the same widget?"""
        assert self.end is not None
        return (
            self.start.content_widget is not None
            and self.start.content_widget is self.end.content_widget
            and self.start.content_offset is not None
            and self.end.content_offset is not None
        )

    @property
    def content_offsets(self) -> tuple[Offset, Offset]:
        """Get the content offset in select order."""
        assert (
            self.end is not None
        ), "Unavailable until there is an end point to the selection"
        start_offset = self.start.content_offset
        end_offset = self.end.content_offset
        assert start_offset is not None
        assert end_offset is not None
        if end_offset.transpose < start_offset.transpose:
            start_offset, end_offset = end_offset, start_offset
        return start_offset, end_offset

    @property
    def select_container(self) -> Widget:
        """A widget that contains both ends of the select."""
        from textual.screen import Screen
        from textual.widget import Widget

        widgets = [
            (
                self.start.content_widget
                if self.start.content_widget is not None
                else self.start.container
            )
        ]
        if self.end is not None:
            widgets.append(
                self.end.content_widget
                if self.end.content_widget is not None
                else self.end.container
            )

        if len(widgets) == 2:
            widget1, widget2 = widgets
            if isinstance(widget1, Screen):
                return widget1
            if isinstance(widget2, Screen):
                return widget2
            try:
                return Widget.get_common_ancestor(widget1, widget2)
            except ValueError:
                return widget1
        else:
            return widgets[0]

    @property
    def selection_bounds(self) -> Shape:
        """A shape which overlays the area of selected text."""

        selection_bounds = Shape.selection_bounds(
            self.select_container.region,
            self.start.pointer_start_offset,
            self.screen_offset,
        )
        return selection_bounds

    @property
    def ordered_offsets(self) -> tuple[Offset, Offset]:
        """Offsets used in selection bounds, in selection order."""
        start_offset = self.start.pointer_start_offset
        end_offset = self.screen_offset

        if start_offset.transpose > end_offset.transpose:
            start_offset, end_offset = end_offset, start_offset

        return start_offset, end_offset

    def update_end(self, pointer_offset: Offset, select_end: SelectEnd) -> SelectState:
        """Update the state with the selection end.

        Args:
            pointer_offset: Current mouse position.
            select_end: Selection end.

        Returns:
            SelectState: New select state.

        """
        return SelectState(pointer_offset, self.start, select_end)

    def _apply_content_selections(self, selections: dict[Widget, Selection]):
        assert (
            self.end is not None
        ), "Unavailable until there is an end point to the selection"
        start_widget = self.start.content_widget
        start_content_offset = self.start.content_offset
        start_offset = self.start.pointer_start_offset

        end_widget = self.end.content_widget
        end_content_offset = self.end.content_offset
        end_offset = self.screen_offset

        if end_offset.transpose < start_offset.transpose:
            start_widget, end_widget = end_widget, start_widget
            start_content_offset, end_content_offset = (
                end_content_offset,
                start_content_offset,
            )

        if start_widget is not None and start_content_offset is not None:
            selections[start_widget] = Selection(start_content_offset, None)
        if end_widget is not None and end_content_offset is not None:
            selections[end_widget] = Selection(None, end_content_offset)

    def _walk_viewport_widgets(self) -> list[Widget] | None:
        """Select painted widgets when both endpoints fit in one viewport.

        Dragging within an existing transcript should depend on the viewport,
        not on how many previous messages remain mounted. Off-screen drags,
        nested scroll regions and gap endpoints use the general selection
        walker, which includes their otherwise hidden text for copying.
        """
        from textual.screen import Screen
        from textual.widget import Widget

        start = self.start.content_widget
        end = self.end.content_widget if self.end is not None else None
        if start is None or end is None or not start.is_attached or not end.is_attached:
            return None
        root = self.select_container
        if isinstance(root, Screen) or not isinstance(root, Widget):
            return None
        screen = start.screen
        if end.screen is not screen:
            return None
        end_ancestors = set(end.walk_ancestors(with_self=True))
        viewport = next(
            (ancestor for ancestor in start.walk_ancestors()
             if isinstance(ancestor, Widget) and ancestor.is_scrollable
             and ancestor in end_ancestors
             and screen.size.region.contains_region(ancestor.content_region)),
            None,
        )
        if viewport is None:
            return None
        region = viewport.content_region
        if (not region.contains_region(start.region)
                or not region.contains_region(end.region)
                or not region.contains_point(self.start.pointer_start_offset)
                or not region.contains_point(self.screen_offset)):
            return None

        visible = screen._compositor.published_widgets
        if start not in visible or end not in visible:
            return None
        bounds = self.selection_bounds
        for widget in visible:
            if (widget is not viewport and widget.is_scrollable
                    and (widget.max_scroll_y > 0 or widget.max_scroll_x > 0)
                    and bounds.overlaps(widget.region)):
                return None
        result = sorted(
            (widget for widget in visible
             if not widget.is_container and widget.allow_select
             and root in widget.walk_ancestors()
             and bounds.overlaps(widget.content_region)),
            key=attrgetter("_selection_order"),
        )
        return result

    def _walk_selected_widgets(self) -> list[Widget]:
        assert (
            self.end is not None
        ), "Unavailable until there is an end point to the selection"

        from textual import errors
        from textual.dom import DOMNode, NoScreen
        from textual.widget import Widget

        viewport_widgets = self._walk_viewport_widgets()
        if viewport_widgets is not None:
            return viewport_widgets

        selection_bounds = self.selection_bounds
        select_container = self.select_container

        # Endpoints sorted by screen position.
        ordered_start, ordered_end = self.ordered_offsets
        start_y = ordered_start.y
        end_y = ordered_end.y

        # Identify the content widgets at each end of the selection, in
        # selection order. Either may be `None` if the pointer was not over a
        # content widget at that end.
        if self.start.pointer_start_offset.transpose <= self.screen_offset.transpose:
            first_content_widget = self.start.content_widget
            last_content_widget = self.end.content_widget
        else:
            first_content_widget = self.end.content_widget
            last_content_widget = self.start.content_widget

        # Every descendant belongs to this selection's screen. Re-discovering
        # that screen by walking the ancestry for every sort/region lookup is
        # costly in nested message widgets. Resolve geometry through its owner
        # once, retaining values only for this synchronous traversal (not across
        # scrolling, layout or DOM changes).
        try:
            find_widget = select_container.screen.find_widget
        except NoScreen:
            find_widget = None
        regions: dict[Widget, Region] = {}

        def layout_region(widget: Widget) -> Region:
            if find_widget is None:
                return widget.region
            try:
                return regions[widget]
            except KeyError:
                try:
                    region = find_widget(widget).region
                except errors.NoWidget:
                    region = NULL_REGION
                regions[widget] = region
                return region

        def get_region(widget: Widget) -> Region:
            if type(widget).region is not Widget.region:
                return widget.region
            return layout_region(widget)

        def get_content_region(widget: Widget) -> Region:
            if type(widget).content_region is not Widget.content_region:
                return widget.content_region
            return get_region(widget).shrink(widget.styles.gutter)

        def get_selection_order(widget: Widget) -> tuple[int, int]:
            if type(widget)._selection_order is not Widget._selection_order:
                return widget._selection_order
            region = layout_region(widget)
            return region.y, region.x

        selected: list[Widget] = []

        def visible_children(root: Widget, root_visible: bool = True) -> Iterable[Widget]:
            if type(root).displayed_and_visible_children is not DOMNode.displayed_and_visible_children:
                return root.displayed_and_visible_children
            # Descendants yielded by this traversal were already checked for
            # visibility by their parent's child list. Don't walk their ancestry
            # again just to rediscover that same inherited value.
            return root._nodes._get_displayed_and_visible(root_visible)

        def ordered_children(root: Widget, root_visible: bool = True) -> Iterable[Widget]:
            """Prune unrelated siblings for a vertical, endpoint-bound range.

            Off-screen drag selections still include every widget *between*
            their actual endpoints, unlike the viewport-only paint shortcut.
            A transcript with thousands of earlier siblings need not check
            their visibility and geometry on every pointer movement.
            """
            if (root is select_container and first_content_widget is not None
                    and last_content_widget is not None
                    and type(root.layout).__name__ in {"VerticalLayout", "StreamLayout"}):
                def branch(widget: Widget) -> Widget | None:
                    while widget.parent is not root:
                        if not isinstance(widget.parent, Widget):
                            return None
                        widget = widget.parent
                    return widget

                first_branch = branch(first_content_widget)
                last_branch = branch(last_content_widget)
                if first_branch is not None and last_branch is not None:
                    siblings = root.children
                    try:
                        first_index = siblings.index(first_branch)
                        last_index = siblings.index(last_branch)
                    except ValueError:
                        pass
                    else:
                        # Only ordinary flow children can be bounded by their
                        # DOM order. Positioned/layered children may be drawn
                        # elsewhere and fall back to the general walker.
                        if all(child.styles.position == "relative" and not child.styles.layer
                               for child in siblings):
                            low, high = sorted((first_index, last_index))
                            visible = set(visible_children(root, root_visible))
                            return sorted(
                                (child for child in siblings[low : high + 1]
                                 if child in visible),
                                key=get_selection_order,
                            )
            return sorted(visible_children(root, root_visible), key=get_selection_order)

        def walk_in_select_order(
            root: Widget, from_widget: Widget | None = None
        ) -> Iterable[Widget]:
            """Walk depth-first, skipping subtrees preceding a known endpoint.

            Entering/exiting a scroll region may select hidden text, so the
            viewport shortcut cannot handle it. The exact starting widget still
            tells us which earlier branches cannot contribute to the selection.
            Keep the original spatial ordering within every sibling list.
            """
            start_branches: dict[Widget, Widget] = {}
            if from_widget is not None:
                branch = from_widget
                while branch is not root:
                    parent = branch.parent
                    if not isinstance(parent, Widget):
                        return
                    start_branches[parent] = branch
                    branch = parent

            def children_from_start(node: Widget) -> Iterable[Widget]:
                children = sorted(
                    visible_children(node), key=get_selection_order
                )
                first_branch = start_branches.get(node)
                if first_branch is not None:
                    try:
                        return children[children.index(first_branch) :]
                    except ValueError:
                        # The endpoint is in a non-displayed/hidden branch.
                        return ()
                return children

            stack: list[Iterator[Widget]] = [iter(children_from_start(root))]
            while stack:
                widget = next(stack[-1], None)
                if widget is None:
                    stack.pop()
                    continue
                yield widget
                if widget.children:
                    stack.append(iter(children_from_start(widget)))

        def collect_range(
            container: Widget,
            from_widget: Widget | None,
            to_widget: Widget | None,
            *,
            from_y: int | None = None,
            to_y: int | None = None,
        ) -> None:
            """Collect selectable descendants between two content widgets.

            Walks `container` in selection order, including selectable
            non-container descendants.

            When the start or end pointer lands on a gap (no content widget),
            `from_y` / `to_y` fall back to a vertical bound on the widget's
            `content_region.y` so the selection grows continuously as the
            pointer moves, rather than snapping to the whole container.

            Args:
                container: Top level widget, that is parent of `from_widget` and `to_widget.
                from_widget: First widget in sslection order or first in selection order.
                to_widget: Last widget in selection order or `None` for end of container.

                from_y: Start `y` of selection, or `None` for top.
                to_y: End `y` of selection, or `None` for end.
            """
            started = from_widget is None and from_y is None
            for descendant in walk_in_select_order(container, from_widget):
                if descendant.is_container or not descendant.allow_select:
                    continue
                widget_y = get_content_region(descendant).y
                if not started:
                    if from_widget is not None:
                        if descendant is from_widget:
                            started = True
                        else:
                            continue
                    else:
                        # from_y bound is active.
                        assert from_y is not None
                        if widget_y >= from_y:
                            started = True
                        else:
                            continue
                if to_widget is None and to_y is not None and widget_y > to_y:
                    return
                selected.append(descendant)
                if to_widget is not None and descendant is to_widget:
                    return

        def visit(root: Widget) -> None:
            """Walk in depth-first order without a recursive closure cycle."""
            stack = [iter(ordered_children(root, root.visible))]
            while stack:
                child = next(stack[-1], None)
                if child is None:
                    stack.pop()
                    continue
                if child.is_container:
                    child_region = get_region(child)
                    if not child_region:
                        continue
                    if not selection_bounds.overlaps(child_region):
                        continue

                    has_hidden_content = child.is_scrollable and (
                        child.max_scroll_y > 0 or child.max_scroll_x > 0
                    )

                    if has_hidden_content:
                        child_top = child_region.y
                        child_bottom = child_region.bottom
                        extends_above = start_y < child_top
                        extends_below = end_y >= child_bottom

                        if extends_above and extends_below:
                            # Selection passes through this container; select
                            # everything inside it.
                            collect_range(child, None, None)
                            continue
                        if extends_above:
                            # Selection enters this container from above;
                            # select from top down to the end content widget,
                            # or to the pointer y if the pointer is on a gap.
                            if last_content_widget is not None:
                                collect_range(child, None, last_content_widget)
                            else:
                                collect_range(child, None, None, to_y=end_y)
                            continue
                        if extends_below:
                            # Selection exits this container below; select
                            # from the start content widget (or the pointer y
                            # if on a gap) down to the end.
                            if first_content_widget is not None:
                                collect_range(child, first_content_widget, None)
                            else:
                                collect_range(child, None, None, from_y=start_y)
                            continue

                    # Both endpoints inside this child, or nothing scrolled
                    # out; fall back to the standard visual walk.
                    stack.append(iter(ordered_children(child)))
                else:
                    if child.allow_select and selection_bounds.overlaps(
                        get_content_region(child)
                    ):
                        selected.append(child)

        visit(select_container)
        return selected
