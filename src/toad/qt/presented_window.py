"""Every window Toad opens over its app window, presented as the screen's width class says.

`toad.screen_width.ScreenWidth` decides, from the app window's width in columns of its text:
NARROW (a phone, or a desktop window as narrow as one) fills the app window as a phone app's
page does, under a header whose ← goes back; WIDE floats a dialog no larger than its screen.
Textual's windows read the same class (its settings panel fills a narrow terminal).

The presentation is applied each time the window is shown, in `setVisible`, which `show`,
`open` and `exec` all reach, so a window has it by inheriting `PresentedWindow` and no caller
presents anything: a window opened from anywhere, and a window added later, is presented the
same way. `tools/qt_inherit_ratchet.py` fails a Qt dialog that does not inherit it.

Tristan, Android, 2026-11-18: Settings opened as a small floating dialog over the chat with one
line of its content showing, and the team window drew part of itself off screen.
"""

from __future__ import annotations

from abc import abstractmethod

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt
from PySide6.QtWidgets import QBoxLayout, QHBoxLayout, QLabel, QLayout, QToolButton, QWidget

from toad.qt.metrics import UiGap
from toad.screen_width import ScreenWidth
from toad.window_presentation import BesideApp, FillsApp, WindowPresentation

def window_width(host: QWidget) -> ScreenWidth:
    """The width class of the window `host`: its width in columns of its font's text."""
    width = host.width() if host.isVisible() and host.width() > 0 else host.screen().availableGeometry().width()
    return ScreenWidth.of(width / max(1, host.fontMetrics().averageCharWidth()))


class QtWindowPresentation(WindowPresentation):
    """How Qt lays a window over the app window, for one width class."""

    @classmethod
    def present(cls, window: PresentedWindow, host: QWidget) -> None:
        """Lay `window` out for this width class before it is shown."""
        window.layout().setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        window.setMinimumSize(0, 0)
        flags = cls.window_flags()
        if window.windowFlags() != flags:
            window.setWindowFlags(flags)
        window.page_header().setVisible(cls.shows_header())
        cls.place(window, host)

    @classmethod
    @abstractmethod
    def window_flags(cls) -> Qt.WindowType: ...

    @classmethod
    @abstractmethod
    def shows_header(cls) -> bool: ...

    @classmethod
    @abstractmethod
    def place(cls, window: QWidget, host: QWidget) -> None:
        """Size and place `window`; also run when the app window resizes or turns while it shows."""


class FilledWindow(QtWindowPresentation, FillsApp):
    """A phone app's page: exactly the app window's area, under the window's own ← header."""

    @classmethod
    def window_flags(cls) -> Qt.WindowType:
        return Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint

    @classmethod
    def shows_header(cls) -> bool:
        return True

    @classmethod
    def place(cls, window: QWidget, host: QWidget) -> None:
        window.setMaximumSize(host.size())
        window.setGeometry(QRect(host.mapToGlobal(QPoint(0, 0)), host.size()))


class FloatingWindow(QtWindowPresentation, BesideApp):
    """A desktop dialog centred over the app: at least half the app window wide and seven
    tenths as tall (more when its own size or its layout asks for more), never past its screen
    less the system's bars. Settings once floated at its layout's 228x165 hint over the chat."""

    least_width = 1 / 2
    least_height = 7 / 10

    @classmethod
    def window_flags(cls) -> Qt.WindowType:
        return Qt.WindowType.Dialog

    @classmethod
    def shows_header(cls) -> bool:
        return False

    @classmethod
    def place(cls, window: QWidget, host: QWidget) -> None:
        # The window's client area, inside the screen less its bars and the window's frame (as
        # thick as the app window's own).
        frame, inside = host.frameGeometry(), host.geometry()
        available = host.screen().availableGeometry().adjusted(
            inside.left() - frame.left(), inside.top() - frame.top(),
            inside.right() - frame.right(), inside.bottom() - frame.bottom())
        hint = window.sizeHint()
        width = min(available.width(), max(window.width(), hint.width(), int(host.width() * cls.least_width)))
        height = min(available.height(), max(window.height(), hint.height(), int(host.height() * cls.least_height)))
        placed = QRect(0, 0, width, height)
        placed.moveCenter(QRect(host.mapToGlobal(QPoint(0, 0)), host.size()).center())
        placed.moveLeft(max(available.left(), min(placed.left(), available.right() + 1 - width)))
        placed.moveTop(max(available.top(), min(placed.top(), available.bottom() + 1 - height)))
        window.setMaximumSize(available.size())
        window.setGeometry(placed)


class PresentedWindow:
    """A window opened over the app window. Listed before the window's Qt dialog class, so its
    `setVisible` presents the window each time it is shown, and its header's ← and Android's
    back key close it as the dialog's own Close does."""

    _page_header: QWidget | None = None
    _presentation: type[QtWindowPresentation] | None = None
    _presentation_host: QWidget | None = None

    def presentation_host(self) -> QWidget:
        """The app window this window is opened over: its parent's window. A window is always
        opened over one, so a window built without a parent is refused when it is shown."""
        parent = self.parentWidget()
        if parent is None:
            raise TypeError(f"{type(self).__qualname__} is shown without the window it opens over "
                            "as its parent")
        return parent.window()

    def page_header(self) -> QWidget:
        """The ← header a filled window shows above its content, built the first time."""
        if self._page_header is None:
            layout = self.layout()
            if not isinstance(layout, QBoxLayout):
                raise TypeError(f"{type(self).__qualname__} is a PresentedWindow without a box layout "
                                "for its page header")
            header = QWidget(self)
            row = QHBoxLayout(header)
            row.setContentsMargins(0, 0, 0, UiGap.normal)
            back = QToolButton(header)
            back.setText("←")
            back.setToolTip("Back")
            back.setAutoRaise(True)
            back.clicked.connect(self.close)
            title = QLabel(self.windowTitle(), header)
            self.windowTitleChanged.connect(title.setText)
            row.addWidget(back)
            row.addWidget(title, 1)
            layout.insertWidget(0, header)
            self._page_header = header
        return self._page_header

    def setVisible(self, visible: bool) -> None:  # noqa: N802 (Qt override)
        if visible and not self.isVisible():
            host = self.presentation_host()
            presentation = QtWindowPresentation.for_width(window_width(host))
            if self._presentation_host is not host:
                host.installEventFilter(self)
                self._presentation_host = host
            self._presentation = presentation
            presentation.present(self, host)
        super().setVisible(visible)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 (Qt override)
        """The app window resized or turned while this window shows: place it again."""
        if (watched is self._presentation_host and self.isVisible() and self._presentation is not None
                and event.type() in (QEvent.Type.Resize, QEvent.Type.Move)):
            self._presentation.place(self, watched)
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        """Android's back key closes the window, as its ← and its Close do."""
        if event.key() == Qt.Key.Key_Back:
            event.accept()
            self.close()
            return
        super().keyPressEvent(event)
