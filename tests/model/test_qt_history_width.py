"""Qt history derives horizontal extent and diff layout from the shared declarations."""

import os
import pickle
from pathlib import Path
from types import SimpleNamespace

from agent_comms.messaging.display_references import ProjectReferences
from pyqt_reactive.widgets.virtual_rows import HtmlRow, VirtualRowView
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from toad.markdown_links import LinkContext
from toad.client.line_blocks import Span, Summary, ToolArgumentRole, ToolVerbRole
from toad.patch import (
    DiffSettings,
    NoWrapMode,
    SplitDiff,
    UnifiedDiff,
    WrapModeEnabled,
    parse_patch,
)
from toad.qt.history import (
    RowPictures,
    HistoryRowDelegate,
    HistoryRows,
    QtHistoryRowBatchRenderTask,
    QtRowPreparation,
)
from toad.qt.lines import QtLineRenderer
from toad.qt.theme import current_scheme


def renderer(settings: DiffSettings) -> QtLineRenderer:
    return QtLineRenderer(
        current_scheme(os.environ),
        LinkContext(Path.cwd(), ProjectReferences()),
        settings,
    ).at_width(80)


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


def test_qt_row_batch_is_data_only_at_the_process_boundary() -> None:
    patch = parse_patch("--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-old\n+new\n")
    preparation = QtRowPreparation(
        (patch,),
        current_scheme(os.environ),
        LinkContext(Path.cwd(), ProjectReferences()),
        DiffSettings(),
        80,
    )
    task = QtHistoryRowBatchRenderTask((preparation,))

    restored = pickle.loads(pickle.dumps(task, protocol=5))

    assert restored.execute()[0].html.startswith("<p")


def test_qt_history_width_comes_from_the_rendered_document(monkeypatch) -> None:
    """A row's extent is what its document came out as when it was laid out: wrapped prose
    stays at the layout width, a `pre` block reports its own. The delegate keeps it with the
    height, so the size hint that reads it lays nothing out."""
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    delegate = HistoryRowDelegate(renderer(DiffSettings()), RowPictures(2 ** 20))
    view = VirtualRowView(delegate)
    font = QFont()
    try:
        delegate.measured_height("wrapped", font, 200, HtmlRow('<p style="white-space:pre-wrap">' + "x" * 200 + "</p>"))
        delegate.measured_height("intrinsic", font, 200, HtmlRow("<pre>" + "x" * 200 + "</pre>"))

        assert delegate.row_extent("wrapped", 200) == 200
        assert delegate.row_extent("intrinsic", 200) > 200
        assert delegate.row_extent("not laid out", 200) == 200
    finally:
        delegate.cleanup()
        view.deleteLater()
        app.quit()


def test_qt_tool_summary_is_clipped_by_the_shared_summary_owner() -> None:
    line_renderer = renderer(DiffSettings()).at_width(20)
    summary = Summary(
        (Span("Run", ToolVerbRole), Span(" " + "argument" * 20, ToolArgumentRole)),
        kept=(Span(" · done"),),
    )

    html = line_renderer.html((summary,))

    assert "argumentargument" not in html
    assert "…" in html
    assert " · done" in html


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
    delegate = HistoryRowDelegate(line_renderer, RowPictures(2 ** 20))
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
