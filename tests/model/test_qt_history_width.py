"""Qt history derives horizontal extent and diff layout from the shared declarations."""

import os
from pathlib import Path
from types import SimpleNamespace

from agent_comms.messaging.display_references import ProjectReferences
from PySide6.QtGui import QFont, QTextDocument
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from toad.markdown_links import LinkContext
from toad.patch import DiffSettings, NoWrapMode, SplitDiff, UnifiedDiff, WrapModeEnabled, parse_patch
from pyqt_reactive.widgets.virtual_rows import VirtualRowView

from toad.qt.history import HistoryRowDelegate, HistoryRows
from toad.qt.lines import QtLineRenderer
from toad.qt.theme import current_scheme


def renderer(settings: DiffSettings) -> QtLineRenderer:
    return QtLineRenderer(
        current_scheme(os.environ),
        LinkContext(Path.cwd(), ProjectReferences()),
        settings,
    ).at_width(200, QFont("monospace", 10))


def test_qt_diff_uses_the_shared_view_and_wrap_families(monkeypatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    patch = parse_patch(
        "--- a/example.py\n+++ b/example.py\n@@ -1 +1 @@\n-"
        + "a" * 100
        + "\n+"
        + "b" * 100
        + "\n"
    )

    unified = renderer(DiffSettings(view=UnifiedDiff, wrap=NoWrapMode)).html((patch,))
    split = renderer(DiffSettings(view=SplitDiff, wrap=WrapModeEnabled)).html((patch,))

    assert unified.count("<tr>") == 2
    assert "white-space:pre-wrap" not in unified
    assert split.count("<tr>") == 1
    assert "white-space:pre-wrap" in split
    app.quit()


def test_qt_history_width_comes_from_the_rendered_document(monkeypatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])

    wrapped = QTextDocument()
    wrapped.setDocumentMargin(0)
    wrapped.setTextWidth(200)
    wrapped.setHtml('<p style="white-space:pre-wrap">' + "x" * 200 + "</p>")
    intrinsic = QTextDocument()
    intrinsic.setDocumentMargin(0)
    intrinsic.setTextWidth(200)
    intrinsic.setHtml("<pre>" + "x" * 200 + "</pre>")

    assert HistoryRowDelegate.document_size(wrapped, 200).width() == 200
    assert HistoryRowDelegate.document_size(intrinsic, 200).width() > 200
    app.quit()


def test_intrinsic_tool_output_gives_the_shared_history_a_horizontal_range(monkeypatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    patch = parse_patch(
        "--- a/example.py\n+++ b/example.py\n@@ -1 +1 @@\n-"
        + "a" * 100
        + "\n+"
        + "b" * 100
        + "\n"
    )
    line_renderer = renderer(DiffSettings(view=UnifiedDiff, wrap=NoWrapMode))
    delegate = HistoryRowDelegate(line_renderer)
    view = VirtualRowView(delegate)
    # HistoryRowDelegate's paint hook belongs to QtHistoryWindow; this proof
    # exercises layout only through the generic virtual-row host.
    view.arrivals = None
    view.row_painted = lambda *args: None
    model = HistoryRows()
    fragment = SimpleNamespace(
        key="patch",
        shown="shown",
        revision=1,
        line_blocks=(patch,),
        clipboard_text="plain fallback",
    )
    model.show((fragment,))
    view.setModel(model)
    view.resize(200, 200)
    view.show()
    app.processEvents()
    delegate._thread_pool.waitForDone()
    # Deliver the queued preparation signal and its one-frame layout timer.
    QTest.qWait(25)
    view.executeDelayedItemsLayout()
    app.processEvents()

    assert view.horizontalScrollBar().maximum() > 0

    delegate.cleanup()
    view.close()
    app.quit()
