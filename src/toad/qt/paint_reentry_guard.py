"""Catch the Python call that re-enters Qt's paint pipeline before the Android
EGL deadlock protector fires.

The crash signature is `QAndroidPlatformOpenGLWindow::eglSurface()` deadlock in
`QBackingStoreRhiSupport::create()` → `QOpenGLContext::makeCurrent()`, which fires
when Qt tries to create a backing-store surface while another widget's paint is
still holding the EGL mutex. The re-entry is usually a Python-side `.show()`,
`.setVisible(True)`, `.setParent()`, `.setGeometry()`, `.raise_()` or `.update()`
during a `paintEvent`/`showEvent`/`polishEvent` chain.

This guard patches those `QWidget` methods and brackets paint-ish events so each
Python call made inside a paint logs its traceback to stderr (→ logcat) and to a
timestamped file under Toad's state folder (`paths.save_error`). The guard adds
no production cost beyond a thread-local counter when it is NOT in a paint.
"""

from __future__ import annotations

import threading
import traceback
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication, QWidget

from toad import paths


_PAINT_EVENT_TYPES = frozenset({
    QEvent.Type.Paint,
    QEvent.Type.Expose,
    QEvent.Type.PlatformSurface,
    QEvent.Type.UpdateRequest,
    QEvent.Type.Polish,
    QEvent.Type.PolishRequest,
    QEvent.Type.Show,
    QEvent.Type.ShowToParent,
    QEvent.Type.WindowActivate,
    QEvent.Type.Move,
    QEvent.Type.Resize,
})


_state = threading.local()


def _depth() -> int:
    return getattr(_state, "depth", 0)


def _describe(widget: Any) -> str:
    try:
        cls = type(widget).__name__
    except Exception:
        cls = "?"
    try:
        name = widget.objectName() if isinstance(widget, QObject) else ""
    except Exception:
        name = ""
    try:
        parent = widget.parent() if isinstance(widget, QObject) else None
        parent_cls = type(parent).__name__ if parent is not None else "<top-level>"
    except Exception:
        parent_cls = "?"
    return f"{cls}(name={name!r}, parent={parent_cls})"


def _record(method: str, widget: Any, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
    depth = _depth()
    if depth <= 0:
        return
    stack = "".join(traceback.format_stack(limit=40))
    paint_chain = getattr(_state, "paint_chain", [])
    chain_str = " -> ".join(paint_chain)
    body = (
        f"[qt-paint-reentry] depth={depth} method={method}\n"
        f"  on {_describe(widget)}\n"
        f"  args={args!r} kwargs={kwargs!r}\n"
        f"  inside paint chain: {chain_str}\n"
        f"  python stack:\n{stack}"
    )
    try:
        print(body, flush=True)
    except Exception:
        pass
    try:
        import sys
        print(body, file=sys.stderr, flush=True)
    except Exception:
        pass
    try:
        paths.save_error(body, "qt_paint_reentry")
    except Exception:
        pass


def _wrap(method_name: str, original: Callable[..., Any]) -> Callable[..., Any]:
    def wrapper(self, *args, **kwargs):
        _record(method_name, self, args, kwargs)
        return original(self, *args, **kwargs)
    wrapper.__name__ = original.__name__
    wrapper.__qualname__ = original.__qualname__
    return wrapper


_WATCHED_METHODS = (
    "show",
    "setVisible",
    "setParent",
    "setGeometry",
    "move",
    "resize",
    "raise_",
    "lower",
    "repaint",
    "update",
    "setStyleSheet",
    "setAttribute",
    "setWindowFlags",
    "setWindowState",
    "activateWindow",
)


_INSTALLED = False


def install() -> None:
    """Patch QWidget methods + install an application event filter.

    Must be called AFTER `QApplication` is constructed (the event filter needs an
    instance) but BEFORE any widget is shown.
    """
    global _INSTALLED
    if _INSTALLED:
        return
    for name in _WATCHED_METHODS:
        original = getattr(QWidget, name, None)
        if original is None:
            continue
        try:
            setattr(QWidget, name, _wrap(name, original))
        except (TypeError, AttributeError):
            # Shiboken sometimes refuses to rebind; log and keep going.
            try:
                import sys
                print(f"[qt-paint-reentry] could not patch QWidget.{name}", file=sys.stderr, flush=True)
            except Exception:
                pass

    app = QApplication.instance()
    if app is not None:
        global _FILTER
        _FILTER = _PaintDepthFilter(app)
        app.installEventFilter(_FILTER)
    _INSTALLED = True


_FILTER: QObject | None = None


class _PaintDepthFilter(QObject):
    """Brackets every Paint/Expose/Polish event that passes through the
    application to count re-entrant depth of the paint pipeline."""

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # type: ignore[override]
        etype = event.type()
        if etype in _PAINT_EVENT_TYPES:
            _state.depth = _depth() + 1
            chain = getattr(_state, "paint_chain", None)
            if chain is None:
                chain = []
                _state.paint_chain = chain
            chain.append(f"{etype.name}@{type(obj).__name__}")
            try:
                return super().eventFilter(obj, event)
            finally:
                _state.depth = _depth() - 1
                chain.pop()
        return super().eventFilter(obj, event)
