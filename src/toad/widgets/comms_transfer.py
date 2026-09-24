"""Inputs for the existing agent-comms export and thread-import operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

from agent_comms.exporting import WireExportFormat, WireExportLimit, WireExportScope
from agent_comms.importing import ImportFormat
from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Select, Static


@dataclass(frozen=True)
class WireExportRequest:
    destination: Path
    format: WireExportFormat
    scope: WireExportScope
    limit: WireExportLimit


@dataclass(frozen=True)
class ThreadImportRequest:
    source: Path
    format: ImportFormat
    name: str
    session_id: str | None
    worktree: str | None


class TransferDialog(ModalScreen):
    DEFAULT_CSS = """
    TransferDialog { align: center middle; background: $background 40%; }
    TransferDialog #transfer-box {
        width: 72; max-width: 95%; height: auto; max-height: 95%;
        padding: 1 2; border: solid $primary; background: $surface;
    }
    TransferDialog Input, TransferDialog Select { width: 1fr; margin-bottom: 1; }
    TransferDialog .transfer-actions { height: auto; width: 1fr; }
    TransferDialog #transfer-error { color: $error; height: auto; }
    """
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [("escape", "cancel", "Cancel")]

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#cancel-transfer")
    def on_cancel(self) -> None:
        self.dismiss(None)

    def _error(self, error: str) -> None:
        self.query_one("#transfer-error", Static).update(error)


class WireExportDialog(TransferDialog):
    """Select destination, representation, scope and an explicit size ceiling."""

    def __init__(self, root: Path) -> None:
        super().__init__()
        self.default_path = root / "exports" / f"wire-{datetime.now(UTC):%Y%m%d-%H%M%S-%f}.jsonl"

    def compose(self) -> ComposeResult:
        with Vertical(id="transfer-box"):
            yield Static("Export wire history (not a Pi session)")
            yield Input(str(self.default_path), id="export-path", placeholder="Destination path")
            yield Select(
                [("JSON Lines (portable wire)", "jsonl"), ("Readable text", "text")],
                value="jsonl", id="export-format", allow_blank=False,
            )
            yield Select(
                [("Everything", "everything"), ("One channel", "channel"),
                 ("One DM", "dm")],
                value="everything", id="export-scope", allow_blank=False,
            )
            yield Input(id="export-target", placeholder="#channel or first,second (for DM)")
            yield Input("5242880", id="export-limit", placeholder="Max bytes; empty = full")
            yield Static("", id="transfer-error")
            yield Button("Export", id="submit-transfer")
            yield Button("Cancel", id="cancel-transfer")

    def on_mount(self) -> None:
        self.query_one("#export-path", Input).focus()

    @on(Select.Changed, "#export-format")
    def on_format_changed(self, event: Select.Changed) -> None:
        path = self.query_one_optional("#export-path", Input)
        if path is not None and path.value in {
            str(self.default_path), str(self.default_path.with_suffix(".txt"))
        }:
            path.value = str(
                self.default_path.with_suffix(".txt")
                if event.value == "text" else self.default_path
            )

    @on(Button.Pressed, "#submit-transfer")
    def action_submit(self) -> None:
        try:
            path = self.query_one("#export-path", Input).value.strip()
            if not path:
                raise ValueError("Choose an output path.")
            kind = self.query_one("#export-scope", Select).value
            target = self.query_one("#export-target", Input).value.strip()
            if kind == "channel":
                scope = WireExportScope.for_channel(target)
            elif kind == "dm":
                participants = [name.strip().removeprefix("@") for name in target.split(",")]
                scope = WireExportScope.for_dm(*participants)
            else:
                scope = WireExportScope.everything()
            value = self.query_one("#export-limit", Input).value.strip()
            limit = WireExportLimit.max_bytes(int(value)) if value else WireExportLimit.full()
            request = WireExportRequest(
                Path(path).expanduser(),
                WireExportFormat(self.query_one("#export-format", Select).value),
                scope, limit,
            )
        except (TypeError, ValueError) as error:
            self._error(str(error))
            return
        self.dismiss(request)


class ThreadImportDialog(TransferDialog):
    """Create one stopped, resumable thread from OpenCode or Codex history."""

    def compose(self) -> ComposeResult:
        with Vertical(id="transfer-box"):
            yield Static("Thread Import: OpenCode export/database or Codex rollout")
            yield Select(
                [("OpenCode", "opencode"), ("Codex", "codex")],
                value="opencode", id="import-format", allow_blank=False,
            )
            yield Input(id="import-source", placeholder="Source JSON, database or rollout JSONL")
            yield Input(id="import-name", placeholder="New thread name")
            yield Input(id="import-session-id", placeholder="Session ID (OpenCode database only)")
            yield Input(id="import-worktree", placeholder="Project directory override (optional)")
            yield Static("", id="transfer-error")
            yield Button("Import stopped thread", id="submit-transfer")
            yield Button("Cancel", id="cancel-transfer")

    def on_mount(self) -> None:
        self.query_one("#import-source", Input).focus()

    @on(Button.Pressed, "#submit-transfer")
    def action_submit(self) -> None:
        source = self.query_one("#import-source", Input).value.strip()
        name = self.query_one("#import-name", Input).value.strip()
        if not source or not name:
            self._error("A source and a new thread name are required.")
            return
        self.dismiss(ThreadImportRequest(
            Path(source).expanduser(),
            ImportFormat(self.query_one("#import-format", Select).value),
            name,
            self.query_one("#import-session-id", Input).value.strip() or None,
            self.query_one("#import-worktree", Input).value.strip() or None,
        ))
