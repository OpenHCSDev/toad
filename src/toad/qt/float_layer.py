"""What floats over Qt's pages: the waits the reader is told about and the latest notices.

Textual floats both over the screen: its toasts, and the loading widget it lays over a
widget that is loading. Qt draws them here, in one layer that is a child of the window
(never a window of its own: a new native window on Android deadlocks the accessibility
bridge against its EGL surface). Nothing in it takes part in the page's layout, so a notice
or a wait never moves the content under it.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget
from pyqt_reactive.protocols.widget_adapters import PyQtWidgetMeta
from pyqt_reactive.theming import ColorScheme, StatusColorRole
from pyqt_reactive.widgets.status_line import NoticeLine

from toad.client.pending import PendingWork, ShowsPending
from toad.qt.activity import ActivitySweep
from toad.qt.lines import QtLineRenderer
from toad.qt.metrics import UiGap


class QtPendingIndicator(ShowsPending, QWidget, metaclass=PyQtWidgetMeta):
    """The work the reader waits on, in words, with Toad's activity sweep under them so the
    reader sees the UI is alive. Hidden until the shared delay passes; cleared when the last
    work it shows ends."""

    def __init__(self, renderer: QtLineRenderer, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Widget)
        self.waiting: list[type[PendingWork]] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(UiGap.dialog, UiGap.tight, UiGap.dialog, UiGap.tight)
        layout.setSpacing(UiGap.tight)
        self.label = QLabel(self)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setWordWrap(True)
        layout.addWidget(self.label)
        self.sweep = ActivitySweep(renderer)
        self.sweep.setParent(self)
        layout.addWidget(self.sweep)
        self.hide()

    def show_pending(self, work: type[PendingWork]) -> None:
        self.waiting.append(work)
        self.label.setText(work.label)
        self.sweep.sweep(True)
        self.show()
        self.raise_()

    def clear_pending(self, work: type[PendingWork]) -> None:
        if work in self.waiting:
            self.waiting.remove(work)
        if self.waiting:
            self.label.setText(self.waiting[-1].label)
            return
        self.sweep.sweep(False)
        self.hide()


class QtNoticeCard(QFrame):
    """One notice floating over the page, in its severity's colour, put away after the
    host's notice seconds or by a tap, as a Textual toast is."""

    def __init__(self, scheme: ColorScheme, text: str, role: StatusColorRole, seconds: float,
                 parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Widget)
        self.text = text
        self.setObjectName("notice")
        self.setStyleSheet(
            f"#notice {{ background: {scheme.to_hex(scheme.panel_bg)};"
            f" border-left: 4px solid {role.color_hex(scheme)}; border-radius: 4px; }}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(UiGap.tight, UiGap.tight, UiGap.tight, UiGap.tight)
        line = NoticeLine(scheme)
        line.setParent(self)
        line.show_status(text, role)
        layout.addWidget(line)
        self.expiry = QTimer(self)
        self.expiry.setSingleShot(True)
        self.expiry.timeout.connect(self.dismiss)
        self.expiry.start(int(seconds * 1000))

    def dismiss(self) -> None:
        self.expiry.stop()
        self.hide()
        self.deleteLater()
        if (layer := self.parentWidget()) is not None:
            layer.adjustSize()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt virtual method name
        self.dismiss()


class QtFloatLayer(ShowsPending, QWidget, metaclass=PyQtWidgetMeta):
    """The window's floating layer: notices stacked newest last, then the wait the reader
    is on, over the top of the pages. It follows the window's size and sits above every
    page; empty, it is hidden so it takes no taps. The waits it shows are the operations
    the host runs (`PendingWork.for_operation`)."""

    #: The most notices shown at once; an older one gives way to a newer one.
    MOST = 3

    def __init__(self, scheme: ColorScheme, renderer: QtLineRenderer, window: QWidget) -> None:
        super().__init__(window)
        self.setWindowFlags(Qt.WindowType.Widget)
        self.scheme = scheme
        self.notices = QVBoxLayout()
        self.notices.setSpacing(UiGap.tight)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(UiGap.dialog, UiGap.dialog, UiGap.dialog, UiGap.dialog)
        layout.setSpacing(UiGap.tight)
        layout.addLayout(self.notices)
        self.pending = QtPendingIndicator(renderer, self)
        self.pending.setAutoFillBackground(True)
        layout.addWidget(self.pending)
        self.follow_scheme(scheme)
        window.installEventFilter(self)
        self.hide()

    def follow_scheme(self, scheme: ColorScheme) -> None:
        """Draw what floats in `scheme` from now on; a notice already shown keeps its colours
        until it goes."""
        self.scheme = scheme
        self.pending.setStyleSheet(f"background: {scheme.to_hex(scheme.panel_bg)}; border-radius: 4px;")

    def post(self, text: str, role: StatusColorRole, seconds: float) -> None:
        cards = [self.notices.itemAt(i).widget() for i in range(self.notices.count())]
        for stale in cards[: max(0, len(cards) - self.MOST + 1)]:
            self.notices.removeWidget(stale)
            stale.deleteLater()
        card = QtNoticeCard(self.scheme, text, role, seconds, self)
        card.destroyed.connect(self.follow_content)
        self.notices.addWidget(card)
        self.follow_content()

    def shown_notices(self) -> tuple[str, ...]:
        """The notices the reader can see now, oldest first."""
        cards = (self.notices.itemAt(i).widget() for i in range(self.notices.count()))
        return tuple(card.text for card in cards if card is not None and not card.isHidden())

    def show_pending(self, work: type[PendingWork]) -> None:
        self.pending.show_pending(work)
        self.follow_content()

    def clear_pending(self, work: type[PendingWork]) -> None:
        self.pending.clear_pending(work)
        self.follow_content()

    def follow_content(self, *_destroyed: object) -> None:
        """Shown while it holds a notice or a wait, sized to them, over the window's top."""
        holding = any(
            (widget := self.notices.itemAt(i).widget()) is not None and not widget.isHidden()
            for i in range(self.notices.count())) or not self.pending.isHidden()
        if not holding:
            self.hide()
            return
        self.place()
        self.show()
        self.raise_()

    def place(self) -> None:
        window = self.parentWidget()
        margins = window.contentsMargins()
        width = window.width() - margins.left() - margins.right()
        self.setFixedWidth(max(1, width))
        self.adjustSize()
        self.move(margins.left(), margins.top())

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt virtual method name
        if watched is self.parentWidget() and event.type() == QEvent.Type.Resize and self.isVisible():
            self.place()
        return super().eventFilter(watched, event)
