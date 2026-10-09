from __future__ import annotations

from typing import TYPE_CHECKING

from textual.content import Content

if TYPE_CHECKING:
    from textual.app import RenderResult

from textual.visual import Visual, VisualType, visualize
from textual.widget import Widget


class Static(Widget, inherit_bindings=False):
    """A widget to display simple static content, or use as a base class for more complex widgets.

    Args:
        content: A Content object, Rich renderable, or string containing console markup.
        expand: Expand content if required to fill container.
        shrink: Shrink content if required to fill container.
        markup: True if markup should be parsed and rendered.
        name: Name of widget.
        id: ID of Widget.
        classes: Space separated list of class names.
        disabled: Whether the static is disabled or not.
    """

    DEFAULT_CSS = """
    Static {
        height: auto;
    }
    """

    def __init__(
        self,
        content: VisualType = "",
        *,
        expand: bool = False,
        shrink: bool = False,
        markup: bool = True,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        super().__init__(
            name=name, id=id, classes=classes, disabled=disabled, markup=markup
        )
        self.set_reactive(Widget.expand, expand)
        self.set_reactive(Widget.shrink, shrink)
        self.__content = content
        self.__visual: Visual | None = None

    @property
    def visual(self) -> Visual:
        """The visual to be displayed.

        Note that the visual is what is ultimately rendered in the widget, but may not be the
        same object set with the `update` method  or `content` property. For instance, if you
        update with a string, then the visual will be a [Content][textual.content.Content] instance.

        """
        if self.__visual is None:
            self.__visual = visualize(self, self.__content, markup=self._render_markup)
        return self.__visual

    @property
    def content(self) -> VisualType:
        """The original content set in the constructor."""
        return self.__content

    @content.setter
    def content(self, content: VisualType) -> None:
        self.__content = content
        self.__visual = visualize(self, content, markup=self._render_markup)
        self.clear_cached_dimensions()
        self.refresh(layout=True)

    def render(self) -> RenderResult:
        """Get a rich renderable for the widget's content.

        Returns:
            A rich renderable.
        """
        return self.visual

    def _render_styles_sensitive(self) -> bool:
        """Only original Content has the native rule-measurement contract.

        Unknown renderers, visual getters and Visual implementations may derive
        content from paint rules. Keep their geometry lifetime conservative.
        Do not create or re-render a visual merely to classify a rule mutation.
        """
        return not self._has_native_content_measurement()

    def _has_native_content_measurement(self) -> bool:
        """Whether Content's text alone supplies this leaf's intrinsic size."""
        return (
            type(self).render is Static.render
            and type(self).visual is Static.visual
            and type(self)._render is Widget._render
            and type(self).get_content_width is Widget.get_content_width
            and type(self).get_content_height is Widget.get_content_height
            and type(self.__visual) is Content
            and self._native_box_measurement
            and not self._container_selection_dependency.styles_sensitive(self)
            and self._native_measurement_layout_hooks
            and not self.is_container
        )

    def update(self, content: VisualType = "", *, layout: bool | None = None) -> None:
        """Update the widget's content area with a string, a Visual (such as [Content][textual.content.Content]), or a [Rich renderable](https://rich.readthedocs.io/en/latest/protocol.html).

        Args:
            content: New content.
            layout: Force a layout operation with `True`, or skip it with `False`.
                By default, unchanged native Content text only repaints; custom
                rendering and measurement retain layout.
        """

        previous_visual = self.__visual
        self.__content = content
        self.__visual = visualize(self, content, markup=self._render_markup)
        if layout is None:
            layout = not (
                self._has_native_content_measurement()
                and type(previous_visual) is Content
                and previous_visual == self.__visual
            )
        self.refresh(layout=layout)
