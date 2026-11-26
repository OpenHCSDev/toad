"""Qt history derives horizontal extent and diff layout from the shared declarations."""

import asyncio
import os
import pickle
from pathlib import Path
from types import SimpleNamespace

from agent_comms.messaging.display_references import ProjectReferences
from pyqt_reactive.widgets.virtual_rows import HtmlRow, VirtualRowView
from PySide6.QtCore import QSize
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication
import pytest

from toad.markdown_links import LinkContext
from toad.client.connection import CoreConnection
from toad.client.line_blocks import Divider, MutedRole, Span, Summary, ToolArgumentRole, ToolVerbRole
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
from toad.render_processes import RenderProcessPool


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
        1,
        (Divider.titled("claude-a", MutedRole),),
    )
    task = QtHistoryRowBatchRenderTask((preparation,))

    restored = pickle.loads(pickle.dumps(task, protocol=5))

    row, = pickle.loads(pickle.dumps(restored.execute(), protocol=5))
    assert row.html.startswith("<p")
    # The row comes back with everything the window reads of it: its first block alone, for
    # the pin's measurement, and the header it pins, under the header the window asks by.
    (leading,), ((header, pinned),) = row.leading, row.pinned
    assert leading.startswith("<p") and "claude-a" in pinned
    assert header == preparation.pinned[0] and hash(header) == hash(preparation.pinned[0])


def test_qt_history_width_comes_from_the_rendered_document(monkeypatch) -> None:
    """A row's extent is what its document came out as when it was laid out: wrapped prose
    stays at the layout width, and so does a `pre` block (source, a tool's output), which
    folds there as the terminal's does; text declared not to wrap reports its own. The
    delegate keeps it with the height, so the size hint that reads it lays nothing out."""
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    delegate = HistoryRowDelegate(renderer(DiffSettings()), RowPictures(2 ** 20),
                                  RenderProcessPool(CoreConnection.helper_start))
    view = VirtualRowView(delegate)
    font = QFont()
    try:
        delegate.measured_height("wrapped", font, 200, HtmlRow('<p style="white-space:pre-wrap">' + "x" * 200 + "</p>"))
        delegate.measured_height("intrinsic", font, 200, HtmlRow('<p style="white-space:pre">' + "x" * 200 + "</p>"))
        for name, source in (("source", "x" * 200), ("words", "word " * 60), ("coded", "<code>" + "x " * 150 + "</code>")):
            delegate.measured_height(name, font, 200, HtmlRow(f"<pre>{source}</pre>"))
            delegate.measured_height(name + " coloured", font, 200, HtmlRow(f'<pre style="color:#888888">{source}</pre>'))

        assert delegate.row_extent("wrapped", 200) == 200
        assert delegate.row_extent("intrinsic", 200) > 200
        for name in ("source", "words", "coded"):
            assert delegate.row_extent(name, 200) == 200, name
            assert delegate.row_extent(name + " coloured", 200) == 200, name
        assert delegate.row_extent("not laid out", 200) == 200
    finally:
        delegate.cleanup()
        view.deleteLater()
        app.quit()


def test_a_row_is_hinted_wider_than_the_window_only_while_code_does_not_wrap(monkeypatch) -> None:
    """A header's table lays out a pixel wider than the width it is given at half of all
    widths (Qt rounds its two rules up). While code wraps, as it does unless the reader says
    otherwise, no row is hinted wider than the layout, so the history has no sideways range
    for a finger to drag; with wrapping off, a row is hinted as wide as it came out."""
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    assert DiffSettings().wrap is WrapModeEnabled
    header = renderer(DiffSettings()).html((Divider.titled("Agent · 2026-11-22 01:11:32", MutedRole),))
    font = QFont()
    hinted = {}
    for settings in (DiffSettings(), DiffSettings(wrap=NoWrapMode)):
        delegate = HistoryRowDelegate(renderer(settings), RowPictures(2 ** 20),
                                      RenderProcessPool(CoreConnection.helper_start))
        view = VirtualRowView(delegate)
        try:
            over = [width for width in range(300, 340)
                    if delegate.measured_height(("header", width), font, width, HtmlRow(header)) and
                    delegate.row_extent(("header", width), width) > width]
            assert over, "this test needs a header Qt lays out wider than its width"
            width = over[0]
            height = delegate.measured_height(("header", width), font, width, HtmlRow(header))
            hinted[settings.wrap] = delegate.hinted(("header", width), QSize(width, height)).width() - width
        finally:
            delegate.cleanup()
            view.deleteLater()
    app.quit()

    assert hinted == {WrapModeEnabled: 0, NoWrapMode: 1}


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
    """A history row is rendered by the app's render processes and by nothing in this process:
    the row a view asks for goes to a worker, lands, and is laid out at its own extent."""
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
    fragment = SimpleNamespace(
        key="patch",
        shown="shown",
        revision=1,
        has_blocks=True,
        line_blocks=(patch,),
        clipboard_text="plain fallback",
        header_blocks=0,
        pinned_dividers=(),
    )

    async def shown() -> None:
        pool = RenderProcessPool(CoreConnection.helper_start, max_workers=1)
        pool.start()
        delegate = HistoryRowDelegate(line_renderer, RowPictures(2 ** 20), pool)
        view = VirtualRowView(delegate)
        # HistoryRowDelegate's paint hook belongs to QtHistoryWindow; this proof
        # exercises layout only through the generic virtual-row host.
        view.has_active_arrivals = False
        view._tap_flash = None
        view._paint_region = None
        view.row_painted = lambda *args: None
        model = HistoryRows()
        try:
            # The worker is another process (spawned here), so this reaches only this one.
            monkeypatch.setattr(QtLineRenderer, "html", lambda *args, **kwargs: pytest.fail(
                "a history row was rendered in the UI process"))
            model.show((fragment,))
            view.setModel(model)
            view.resize(200, 200)
            view.show()
            async with asyncio.timeout(60):
                while not view.horizontalScrollBar().maximum():
                    app.processEvents()  # the paint that asks, the one-frame layout timer
                    view.executeDelayedItemsLayout()
                    await asyncio.sleep(0.01)  # the worker's answer
        finally:
            delegate.cleanup()
            view.deleteLater()
            await pool.aclose()

    asyncio.run(shown())
    app.quit()
