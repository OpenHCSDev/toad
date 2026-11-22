"""Android's pixel-sized theme fonts become point sizes of the same number, so they follow the
logical DPI where Qt puts the remainder of a rounded pixel ratio (`toad.qt.android`)."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from toad.qt.android import fonts_in_points, qt_widget_classes  # noqa: E402


@pytest.fixture
def application():
    app = QApplication.instance() or QApplication([])
    kept = QApplication.font()
    yield app
    QApplication.setFont(kept)


def test_the_theme_fonts_keep_their_number_in_points_and_a_class_keeps_its_own(application):
    default = QFont(QApplication.font())
    default.setPixelSize(16)
    QApplication.setFont(default)
    button = QFont(default)
    button.setPixelSize(20)
    button.setBold(True)
    QApplication.setFont(button, "QPushButton")

    fonts_in_points()

    assert (QApplication.font().pixelSize(), QApplication.font().pointSizeF()) == (-1, 16.0)
    kept = QApplication.font("QPushButton")
    assert (kept.pixelSize(), kept.pointSizeF(), kept.bold()) == (-1, 20.0, True)
    assert QApplication.font("QLabel").pointSizeF() == 16.0


def test_qt_names_its_own_widget_classes_and_none_of_toads():
    names = set(qt_widget_classes())
    assert {"QPushButton", "QLabel", "QListView", "QAbstractItemView"} <= names
    assert not any(name.startswith("Qt") or "Toad" in name for name in names)
