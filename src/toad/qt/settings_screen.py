"""Qt settings screen — a thin renderer over `SettingsSchema`.

Opened by `QtToadApp.edit_settings` (overrides the `ClientApplication` stub);
the hamburger menu's `SettingsAction` fires that capability. Both frontends
read/write the same `SavedSettings`; this Qt surface iterates the shared
`SettingsSchema` and dispatches each row to a `QtSettingsEditor` family member
by its declared `SettingsRowKind`.

Writes go through `SettingsRowSchema.write` / `.toggle`, which validate and
publish `PreferenceChanged` on the shared event stream — Textual's own forms
see the change for free. No parallel save path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Iterator, Self

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDoubleValidator, QIntValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from toad.client.settings_schema import (
    BoolRowKind,
    ChoicesRowKind,
    FloatRowKind,
    IntRowKind,
    SchemeChoiceRowKind,
    SettingsPageSchema,
    SettingsRowKind,
    SettingsRowSchema,
    SettingsSchema,
    StrRowKind,
)

if TYPE_CHECKING:
    from toad.qt.window import QtToadApp


class QtSettingsEditor(QWidget):
    """A Qt widget that renders one `SettingsRowSchema` and sends its edits.

    Family dispatch: each member is decorated with `@shows(KindClass, ...)` to
    declare the `SettingsRowKind` classes it handles. `for_row(row, app, parent)`
    picks the first member whose declaration claims the row's kind and
    instantiates it.

    Note: a class-decorator registration is used instead of the usual `shows=`
    class keyword because PySide6's `shiboken` metaclass refuses extra kwargs
    on class creation.
    """

    shows: ClassVar[tuple[type[SettingsRowKind], ...]] = ()
    _registry: ClassVar[list[type["QtSettingsEditor"]]] = []

    @classmethod
    def members(cls) -> Iterator[type["QtSettingsEditor"]]:
        yield from cls._registry

    @classmethod
    def for_row(
        cls, row: SettingsRowSchema, app: "QtToadApp", parent: QWidget | None = None
    ) -> "QtSettingsEditor":
        for member in cls._registry:
            if any(isinstance(row.kind, declared) for declared in member.shows):
                return member(row, app, parent)
        raise LookupError(f"No QtSettingsEditor shows row kind {type(row.kind).__name__}")

    def __init__(
        self, row: SettingsRowSchema, app: "QtToadApp", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.row = row
        self.app = app
        self._build()
        self.paint()

    def _build(self) -> None:  # pragma: no cover - overridden
        raise NotImplementedError

    def paint(self) -> None:  # pragma: no cover - overridden
        raise NotImplementedError


def shows(*kinds: type[SettingsRowKind]):
    """Decorator: register a `QtSettingsEditor` subclass for these kind classes."""

    def wrap(cls: type[QtSettingsEditor]) -> type[QtSettingsEditor]:
        cls.shows = kinds
        QtSettingsEditor._registry.append(cls)
        return cls

    return wrap


@shows(BoolRowKind)
class QtBoolEditor(QtSettingsEditor):
    def _build(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.box = QCheckBox(self)
        self.box.toggled.connect(self._on_toggled)
        layout.addWidget(self.box)
        layout.addStretch(1)

    def paint(self) -> None:
        self.box.blockSignals(True)
        try:
            self.box.setChecked(bool(self.row.value))
        finally:
            self.box.blockSignals(False)

    def _on_toggled(self, checked: bool) -> None:
        self.row.write(checked)


@shows(IntRowKind)
class QtIntEditor(QtSettingsEditor):
    def _build(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.field = QLineEdit(self)
        self.field.setValidator(QIntValidator(self))
        self.field.editingFinished.connect(self._on_finished)
        layout.addWidget(self.field)
        hint = self.row.bounds_text
        if hint:
            layout.addWidget(QLabel(f"  ({hint})", self))

    def paint(self) -> None:
        self.field.blockSignals(True)
        try:
            self.field.setText(str(self.row.value) if self.row.value is not None else "")
        finally:
            self.field.blockSignals(False)

    def _on_finished(self) -> None:
        text = self.field.text().strip()
        if not text:
            return
        try:
            self.row.write(int(text))
        except (ValueError, Exception):
            self.paint()


@shows(FloatRowKind)
class QtFloatEditor(QtSettingsEditor):
    def _build(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.field = QLineEdit(self)
        self.field.setValidator(QDoubleValidator(self))
        self.field.editingFinished.connect(self._on_finished)
        layout.addWidget(self.field)
        hint = self.row.bounds_text
        if hint:
            layout.addWidget(QLabel(f"  ({hint})", self))

    def paint(self) -> None:
        self.field.blockSignals(True)
        try:
            self.field.setText(str(self.row.value) if self.row.value is not None else "")
        finally:
            self.field.blockSignals(False)

    def _on_finished(self) -> None:
        text = self.field.text().strip()
        if not text:
            return
        try:
            self.row.write(float(text))
        except (ValueError, Exception):
            self.paint()


@shows(StrRowKind)
class QtStrEditor(QtSettingsEditor):
    def _build(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.field = QLineEdit(self)
        self.field.editingFinished.connect(self._on_finished)
        layout.addWidget(self.field)

    def paint(self) -> None:
        self.field.blockSignals(True)
        try:
            self.field.setText(str(self.row.value) if self.row.value is not None else "")
        finally:
            self.field.blockSignals(False)

    def _on_finished(self) -> None:
        try:
            self.row.write(self.field.text())
        except Exception:
            self.paint()


@shows(ChoicesRowKind)
class QtChoicesEditor(QtSettingsEditor):
    def _build(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.combo = QComboBox(self)
        kind = self.row.kind
        assert isinstance(kind, ChoicesRowKind)
        for label, value in kind.options:
            self.combo.addItem(label, value)
        self.combo.currentIndexChanged.connect(self._on_changed)
        layout.addWidget(self.combo)

    def paint(self) -> None:
        self.combo.blockSignals(True)
        try:
            value = self.row.value
            for index in range(self.combo.count()):
                if self.combo.itemData(index) == value:
                    self.combo.setCurrentIndex(index)
                    return
            self.combo.setCurrentIndex(-1)
        finally:
            self.combo.blockSignals(False)

    def _on_changed(self, index: int) -> None:
        if index < 0:
            return
        try:
            self.row.write(self.combo.itemData(index))
        except Exception:
            self.paint()


@shows(SchemeChoiceRowKind)
class QtSchemeChoiceEditor(QtSettingsEditor):
    """Scheme names come from the running app, not the row; options rebuild on paint."""

    def _build(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.combo = QComboBox(self)
        self.combo.setEditable(True)  # a value not in the list still shows
        self.combo.currentTextChanged.connect(self._on_changed)
        layout.addWidget(self.combo)

    def paint(self) -> None:
        self.combo.blockSignals(True)
        try:
            self.combo.clear()
            schemes = list(getattr(self.app.colours, "schemes", ()))
            self.combo.addItems(schemes)
            current = str(self.row.value or "")
            self.combo.setEditText(current)
        finally:
            self.combo.blockSignals(False)

    def _on_changed(self, text: str) -> None:
        try:
            self.row.write(text)
        except Exception:
            self.paint()


class QtSettingsPage(QWidget):
    """One tab's worth of rows, laid out label-and-editor per row."""

    def __init__(
        self,
        app: "QtToadApp",
        page: SettingsPageSchema,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.app = app
        self.page = page
        self._row_widgets: list[tuple[SettingsRowSchema, QWidget, QWidget, QtSettingsEditor]] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        inner = QWidget(scroll)
        form = QFormLayout(inner)
        form.setContentsMargins(8, 8, 8, 8)
        form.setSpacing(6)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        for row in page.rows:
            label_widget = QLabel(row.label, inner)
            label_widget.setWordWrap(True)
            if row.help:
                label_widget.setToolTip(row.help)
            editor = QtSettingsEditor.for_row(row, app, inner)
            form.addRow(label_widget, editor)
            self._row_widgets.append((row, label_widget, editor, editor))
        scroll.setWidget(inner)
        outer.addWidget(scroll)

    def apply_filter(self, term: str) -> int:
        """Hide rows whose search text does not match `term`. Returns matched count."""
        needle = term.strip().lower()
        shown = 0
        for row, label_widget, editor_widget, _ in self._row_widgets:
            visible = not needle or needle in row.search_text or needle in row.label.lower()
            label_widget.setVisible(visible)
            editor_widget.setVisible(visible)
            if visible:
                shown += 1
        return shown

    def repaint_all(self) -> None:
        for _, _, _, editor in self._row_widgets:
            editor.paint()


class QtSettingsScreen(QDialog):
    """Modal settings editor. One tab per `SettingsPageSchema`; each tab holds a
    search-filterable scroll of label-and-editor rows. Discard rolls back unsaved
    edits; closing saves (the file is written by `SavedSettings` on change)."""

    closed = Signal()

    def __init__(self, app: "QtToadApp", parent: QWidget | None = None) -> None:
        super().__init__(parent or app)
        self.setWindowFlags(Qt.WindowType.Dialog)
        self.setWindowTitle("Settings")
        self.app = app
        self.schema = SettingsSchema(app.saved_settings)
        self._pages: list[QtSettingsPage] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        self.search = QLineEdit(self)
        self.search.setPlaceholderText("Search settings")
        self.search.textChanged.connect(self._on_search_changed)
        layout.addWidget(self.search)

        self.tabs = QTabWidget(self)
        for page in self.schema.pages():
            widget = QtSettingsPage(app, page, self.tabs)
            title = page.title or "Settings"
            self.tabs.addTab(widget, title)
            self._pages.append(widget)
        layout.addWidget(self.tabs, stretch=1)

        buttons = QDialogButtonBox(self)
        discard_btn = buttons.addButton(
            "Discard changes", QDialogButtonBox.ButtonRole.ResetRole
        )
        close_btn = buttons.addButton(QDialogButtonBox.StandardButton.Close)
        discard_btn.clicked.connect(self._on_discard)
        close_btn.clicked.connect(self._on_close)
        layout.addWidget(buttons)

    def _on_search_changed(self, text: str) -> None:
        for page in self._pages:
            page.apply_filter(text)

    def _on_discard(self) -> None:
        self.schema.discard()
        for page in self._pages:
            page.repaint_all()

    def _on_close(self) -> None:
        self.schema.finish()
        self.accept()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self.closed.emit()
        super().closeEvent(event)
