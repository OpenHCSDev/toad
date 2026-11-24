"""The transfer forms both frontends inherit: each transfer's heading, the fields it asks
for (labels, placeholders, defaults, choices), and how the answers become its typed
request. Textual's `TransferDialog` and Qt's `QtTransferDialog` add only native widgets,
reading those widgets, and how a composed request leaves the dialog.
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar, Self

from agent_comms.installer.harness_install import Harness
from agent_comms.messaging.exporting import (
    ChannelScope,
    DmScope,
    EverythingScope,
    FullLimit,
    JsonlFormat,
    MaxBytesLimit,
    TextFormat,
    WireExportFormat,
    WireExportScope,
)
from agent_comms.nominal.declared_family import DeclaredFamily
from agent_comms.nominal.field_codec import FieldCodec
from agent_comms.registry.thread_results import ImportDirectory
from agent_comms.registry.thread_text import ExpectedSession

from toad.client.connection import CapturedSource
from toad.client.transfers import ThreadImportRequest, Transfer, WireExportRequest

# What an export's choices offer.

class ExportFormatInput(DeclaredFamily, affix="FormatInput"):
    """UI labels and default filenames, not another wire-format identity."""

    label: ClassVar[str]
    suffix: ClassVar[str]

    @classmethod
    def destination(cls, stem: Path) -> Path:
        return stem.with_suffix(cls.suffix)

    @classmethod
    @abstractmethod
    def format(cls) -> WireExportFormat: ...


class JsonlFormatInput(ExportFormatInput):
    label = "JSON Lines (.jsonl)"
    suffix = ".jsonl"

    @classmethod
    def format(cls) -> JsonlFormat:
        return JsonlFormat()


class TextFormatInput(ExportFormatInput):
    label = "Readable text"
    suffix = ".txt"

    @classmethod
    def format(cls) -> TextFormat:
        return TextFormat()


class ExportScopeInput(DeclaredFamily, affix="ScopeInput"):
    """The dialog's human input grammar; Core still resolves the wire scope."""

    label: ClassVar[str]

    @classmethod
    @abstractmethod
    def parse(cls, target: str) -> WireExportScope: ...


class EverythingScopeInput(ExportScopeInput):
    label = "Everything"

    @classmethod
    def parse(cls, target: str) -> EverythingScope:
        return EverythingScope()


class ChannelScopeInput(ExportScopeInput):
    label = "One channel"

    @classmethod
    def parse(cls, target: str) -> ChannelScope:
        return ChannelScope(target)


class DmScopeInput(ExportScopeInput):
    label = "One DM"

    @classmethod
    def parse(cls, target: str) -> DmScope:
        first, second = (name.strip().removeprefix("@") for name in target.split(","))
        return DmScope((first, second))


# The forms.

class TransferForm:
    """One transfer's input form. A frontend dialog inherits a member and supplies the
    native reads below, `show_error`, and `submit` (how the request leaves the dialog).

    `request_kind` is the `Transfer` member the form composes; each form names it, and
    every frontend's dialog for the form inherits it.
    """

    heading: ClassVar[str]
    submit_label: ClassVar[str]
    request_kind: ClassVar[type[Transfer] | None] = None
    selected: CapturedSource

    @classmethod
    def for_kind(cls, kind: type[Transfer]) -> type[Self]:
        """The member of this frontend's dialog family that composes `kind`."""
        def members(family: type[TransferForm]) -> Iterator[type[TransferForm]]:
            yield family
            for member in family.__subclasses__():
                yield from members(member)
        for member in members(cls):
            if member.request_kind is kind:
                return member
        raise LookupError(f"No {cls.__name__} composes {kind.declared_name}")

    def begin(self, selected: CapturedSource) -> None:
        """The route the composed request runs against."""
        self.selected = selected

    @abstractmethod
    def compose_request(self) -> Transfer:
        """The typed request from the answers; a ValueError/TypeError says what is wrong."""

    @abstractmethod
    def show_error(self, text: str) -> None:
        """Show why the answers were refused."""

    @abstractmethod
    def submit(self, request: Transfer) -> None:
        """Hand the composed request on and close."""

    def confirm_request(self) -> None:
        try:
            request = self.compose_request()
        except (TypeError, ValueError) as error:
            self.show_error(str(error) or "Invalid input.")
            return
        self.submit(request)


class WireExportForm(TransferForm):
    """Select destination, representation, scope and an explicit size ceiling."""

    heading = "Export message history (not a Pi session)"
    submit_label = "Export"
    request_kind = WireExportRequest
    default_format: ClassVar[type[ExportFormatInput]] = JsonlFormatInput
    default_scope: ClassVar[type[ExportScopeInput]] = EverythingScopeInput
    destination_placeholder = "Destination path"
    target_placeholder = "#channel or first,second (for DM)"
    limit_default = "5242880"
    limit_placeholder = "Max bytes; empty = full"

    destination_stem: Path

    def begin(self, selected: CapturedSource) -> None:
        """A fresh, timestamped destination stem under the route's exports directory."""
        super().begin(selected)
        self.destination_stem = selected.root / "exports" / f"wire-{datetime.now(UTC):%Y%m%d-%H%M%S-%f}"

    @property
    def default_destination(self) -> str:
        return str(self.default_format.destination(self.destination_stem))

    @staticmethod
    def format_options() -> Iterator[tuple[str, type[ExportFormatInput]]]:
        return ((choice.label, choice) for choice in ExportFormatInput.members_with(ExportFormatInput))

    @staticmethod
    def scope_options() -> Iterator[tuple[str, type[ExportScopeInput]]]:
        return ((choice.label, choice) for choice in ExportScopeInput.members_with(ExportScopeInput))

    def destination_for_format(self, current: str, chosen: type[ExportFormatInput]) -> str:
        """A destination still at some format's default follows the chosen format; one the
        user typed stays."""
        defaults = {str(choice.destination(self.destination_stem)) for _, choice in self.format_options()}
        return str(chosen.destination(self.destination_stem)) if current in defaults else current

    @abstractmethod
    def destination_text(self) -> str: ...

    @abstractmethod
    def target_text(self) -> str: ...

    @abstractmethod
    def limit_text(self) -> str: ...

    @abstractmethod
    def chosen_format(self) -> type[ExportFormatInput]: ...

    @abstractmethod
    def chosen_scope(self) -> type[ExportScopeInput]: ...

    def compose_request(self) -> Transfer:
        path = self.destination_text().strip()
        if not path:
            raise ValueError("Choose an output path.")
        scope = self.chosen_scope().parse(self.target_text().strip())
        limit_text = self.limit_text().strip()
        limit = MaxBytesLimit(int(limit_text)) if limit_text else FullLimit()
        return self.request_kind(Path(path).expanduser(), self.chosen_format().format(), scope, limit)


class ThreadImportForm(TransferForm):
    """Create one stopped, resumable thread from a stored harness session."""

    heading = "Import a saved session"
    submit_label = "Import stopped thread"
    request_kind = ThreadImportRequest
    source_placeholder = "Source JSON, database or rollout JSONL"
    name_placeholder = "New thread name"
    session_placeholder = "Session ID (OpenCode database only)"
    worktree_placeholder = "Project directory override (optional)"

    @staticmethod
    def harness_options() -> Iterator[tuple[str, type[Harness]]]:
        return ((harness.declared_name, harness) for harness in Harness.members_with(Harness))

    @abstractmethod
    def source_text(self) -> str: ...

    @abstractmethod
    def name_text(self) -> str: ...

    @abstractmethod
    def session_text(self) -> str: ...

    @abstractmethod
    def worktree_text(self) -> str: ...

    @abstractmethod
    def chosen_harness(self) -> type[Harness]: ...

    def compose_request(self) -> Transfer:
        source, name = self.source_text().strip(), self.name_text().strip()
        if not source or not name:
            raise ValueError("A source and a new thread name are required.")
        return self.request_kind(
            Path(source).expanduser(),
            self.chosen_harness(),
            name,
            FieldCodec.decode(ExpectedSession, self.session_text().strip() or None),
            FieldCodec.decode(ImportDirectory, self.worktree_text().strip() or None),
        )
