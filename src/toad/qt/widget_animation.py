"""A target on the app's animation clock that decorates one Qt widget lives no longer than it.

The clock (`QtToadApp.animation_clock`, one QTimer on the window) outlives the widgets its
targets move: a conversation's history window or its queue rows are destroyed when the tab
closes or the app shuts down, while the window's timer still ticks. A tick that then asked the
widget anything (`isVisible` for the clock's cadence) read freed C++ memory: the shipped app
exited with SIGSEGV at shutdown. Each target binds itself to its widget here once: the widget's
`destroyed` stops every animation of the target on the clock, and a widget whose C++ side is
gone is never touched.
"""

from __future__ import annotations

import shiboken6
from PySide6.QtGui import QScreen
from PySide6.QtWidgets import QWidget
from ui_theme.clock import AnimationClock


def frame_interval(screen: QScreen | None) -> float:
    """Seconds between the frames `screen` shows: one over its refresh rate (a Pixel 8a's 120 Hz),
    or 60 Hz where it reports none (offscreen, some remote displays). Motion ticks at it
    (`ui_theme.effects.DisplayRate`); the window's clock and the activity sweep both read it here."""
    rate = screen.refreshRate() if screen is not None else 0.0
    return 1 / (rate if rate >= 20 else 60)


class WidgetAnimation:
    """A clock target whose frames move `widget`, alive on the clock only while the widget is."""

    widget: QWidget

    def bind_widget(self, widget: QWidget, clock: AnimationClock) -> None:
        """Bind before the first `clock.start`: the widget's destruction stops this target."""
        self.widget = widget
        widget.destroyed.connect(lambda *_: clock.stop(self))

    @property
    def widget_alive(self) -> bool:
        return shiboken6.isValid(self.widget)

    @property
    def animation_visible(self) -> bool:
        return self.widget_alive and self.widget.isVisible()
