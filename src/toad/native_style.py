"""A widget's look is its bases.

Each recurring style fact is one mixin. Layout mixins extend Textual's cooperative
``apply_native_layout``; theme mixins declare ``native_theme``, which Textual's node
collects along the MRO with the most derived class last.
"""

from abc import abstractmethod
from collections.abc import Iterable

from textual.css.native import DeclaresTheme, Keyword, NativeDeclaration, TextVariable, Variable
from textual.css.styles import Styles
from textual.view import AUTO, FILL
from textual.widget import Widget
from ui_theme.scheme import MutedColour, PrimaryColour, SecondaryColour, SurfaceColour


class AutoHeight(Widget):
    """Sizes to its content's height."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.height = AUTO


class AutoWidth(Widget):
    """Sizes to its content's width."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.width = AUTO


class FillWidth(Widget):
    """Takes the width its container has left."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.width = FILL


class FillHeight(Widget):
    """Takes the height its container has left."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.height = "1fr"


class OneRow(Widget):
    """Occupies exactly one terminal row."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.height = 1


class TwoRows(Widget):
    """Occupies exactly two terminal rows, for a title and its detail beneath it."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.height = 2


class SidePadding(Widget):
    """One cell of padding on the left and right."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.padding = (0, 1)


class NoPadding(Widget):
    """Flush against its own border."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.padding = 0


class SideMargin(Widget):
    """One cell of margin on the left and right."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.margin = (0, 1)


class NoMargin(Widget):
    """Flush against its neighbours."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.margin = 0


class PointerCursor(Widget):
    """Clickable: the pointer shows it."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.pointer = "pointer"


class NoWrap(Widget):
    """Text stays on its line."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.text_wrap = "nowrap"


class EllipsisOverflow(Widget):
    """Text cut at the edge ends in an ellipsis."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.text_overflow = "ellipsis"


class StartsHidden(Widget):
    """Not displayed until its owner shows it."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.display = "none"


class ComposedWhenShown(Widget):
    """Builds its children the first time it is shown. Most tabs never show it, and a hidden
    widget's children cost their mount, styling and messages in every tab all the same."""

    children_built: bool = False

    @abstractmethod
    def shown_children(self) -> Iterable[Widget]:
        """The children it shows, mounted on its first showing."""

    def show(self, shown: bool) -> None:
        """Display it or not; its children are mounted, synchronously into the tree, before
        it first displays."""
        if shown and not self.children_built:
            self.children_built = True
            self.mount_all(self.shown_children())
        self.display = shown


class ScreenOverlay(Widget):
    """Floats above the screen's flow."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.overlay = "screen"


class HiddenOverflow(Widget):
    """Clips what exceeds it, with no scrollbars."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.overflow_x = self.styles.overflow_y = "hidden"


class DockedBottom(Widget):
    """Docked to its container's bottom edge."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.dock = "bottom"


class CenteredChildren(Widget):
    """Lays its children out in its centre."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.align = ("center", "middle")


class CenteredContent(Widget):
    """Draws its own content in its centre."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.content_align = ("center", "middle")


class CenteredText(Widget):
    """Centres each of its own rows.

    Not CenteredContent: that centres the whole content box inside the widget, which an
    AutoWidth widget has already shrunk to its longest row, so a shorter row still starts
    at the left. Each row is centred against the widest one here.
    """

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.text_align = "center"


class SpacedAbove(Widget):
    """One blank row above it."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.margin = (1, 0, 0, 0)


class SpacedBelow(Widget):
    """One blank row below it."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.margin = (0, 0, 1, 0)


class SpacedAround(Widget):
    """One blank row above and below it."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.margin = (1, 0)


class RightPadding(Widget):
    """One cell of padding on its right."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.padding = (0, 1, 0, 0)


class RightMargin(Widget):
    """One cell of margin on its right."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.margin = (0, 1, 0, 0)


class StableGutter(Widget):
    """Reserves its scrollbar's space whether or not it scrolls."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.scrollbar_gutter = "stable"


class NoScrollbars(Widget):
    """Scrolls without drawing scrollbars."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.scrollbar_size_vertical = self.styles.scrollbar_size_horizontal = 0


class FullWidth(Widget):
    """Spans its container's whole width."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.width = "100%"


class ScrollsVertically(Widget):
    """Scrolls vertically when its content is taller."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.overflow_y = "auto"


class ClipOverflow(Widget):
    """Text cut at the edge is clipped without a marker."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.text_overflow = "clip"


class Bold(Widget):
    """Bold text."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.text_style = "bold"


class MutedText(DeclaresTheme):
    """Text in the theme's muted ink."""

    native_theme = (NativeDeclaration.of(Styles.color, TextVariable(MutedColour.name)),)


class SecondaryText(DeclaresTheme):
    """Text in the theme's secondary ink."""

    native_theme = (NativeDeclaration.of(Styles.color, TextVariable(SecondaryColour.name)),)


class PrimaryText(DeclaresTheme):
    """Text in the theme's primary ink."""

    native_theme = (NativeDeclaration.of(Styles.color, TextVariable(PrimaryColour.name)),)


class Borderless(DeclaresTheme):
    """No border."""

    native_theme = (NativeDeclaration.of(Styles.border, Keyword("none")),)


class TransparentBackground(DeclaresTheme):
    """Shows whatever is behind it."""

    native_theme = (NativeDeclaration.of(Styles.background, Keyword("transparent")),)


class SurfaceBackground(DeclaresTheme):
    """Painted in the theme's surface colour."""

    native_theme = (NativeDeclaration.of(Styles.background, Variable(SurfaceColour.name)),)
