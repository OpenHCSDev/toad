"""Qt's first frame: the banner on the theme's background, painted before the client loads.

Loading the client (Core's wire records, the transport, every view) takes most of a
phone's start, about eight seconds at its speed, and nothing could paint until it finished.
The entry paints this window first, from Qt and the theme alone, then loads the client;
the window steps aside the moment the client's own window is shown."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget
from ui_theme.scheme import BackgroundColour, ColourScheme, MutedColour, PrimaryColour

from toad.qt.banner import Banner
from toad.qt.glyph_fonts import install_glyph_fonts


class QtSplash(QWidget):
    """The window shown while the client loads: the welcome's banner and one quiet line."""

    def __init__(self, scheme: ColourScheme) -> None:
        super().__init__()
        self.background = QColor(BackgroundColour.rgb(scheme).hex)
        layout = QVBoxLayout(self)
        layout.addStretch(1)
        layout.addWidget(Banner(PrimaryColour.rgb(scheme).hex))
        loading = QLabel("Loading…", alignment=Qt.AlignmentFlag.AlignHCenter)
        loading.setStyleSheet(f"color: {MutedColour.rgb(scheme).hex};")
        layout.addWidget(loading)
        layout.addStretch(1)

    def paintEvent(self, event) -> None:
        QPainter(self).fillRect(self.rect(), self.background)

    @classmethod
    def shown(cls, application: QApplication, scheme: ColourScheme) -> QtSplash:
        """Show the first frame and paint it now: the client's load holds the thread next,
        so the frame must be on screen before this returns. The bundled glyph fonts are
        registered first, so the banner draws in them from the first frame on."""
        install_glyph_fonts(application)
        splash = cls(scheme)
        splash.resize(application.primaryScreen().availableSize())
        splash.show()
        splash.repaint()
        application.processEvents()
        application.installEventFilter(StepAside(splash))
        return splash


class StepAside(QObject):
    """Closes the first frame when any other window is shown: the client's window has
    taken over."""

    def __init__(self, splash: QtSplash) -> None:
        super().__init__(splash)
        self.splash = splash

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (event.type() == QEvent.Type.Show and isinstance(watched, QWidget)
                and watched.isWindow() and watched is not self.splash):
            QApplication.instance().removeEventFilter(self)
            self.splash.close()
            self.splash.deleteLater()
        return False
