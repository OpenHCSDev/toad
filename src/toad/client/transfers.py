"""The toolkit-neutral transfer family: what a transfer is, how it runs, and the host
contract both frontends implement. Toolkit-specific dialogs (Textual `TransferDialog` in
`toad.widgets.comms_transfer`, Qt `QtTransferDialog` in `toad.qt.transfer`) consume the
same `Transfer` members and route submitted requests back through `TransferHost.open_transfer`
and `TransferHost.start_transfer_task`.
"""

from __future__ import annotations

import asyncio
from abc import abstractmethod
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from agent_comms.cli_verbs.cli_result import CliResult
from agent_comms.registry.thread_results import ImportDirectory, ThreadImported
from agent_comms.installer.harness_install import Harness
from agent_comms.messaging.exporting import (
    WireExportFormat,
    WireExportLimit,
    WireExportProvenance,
    WireExportScope,
)
from agent_comms.nominal.declared_family import DeclaredFamily
from agent_comms.registry.thread_text import ExpectedSession
from agent_comms.transport.progress import CancellableWireExport, WireExportCancelled
from agent_comms.transport.tools.sidebar import CommsExportWireTool, CommsImportThreadTool
from toad.client.connection import CapturedSource, CoordinationAccess
from toad.client.host import CommsHost
from toad.core import events as core_events
from toad.work_preparation import PreparationRuntime

class TransferProgress:
    """A transfer's shared progress capability. The default is not cancellable; an export's
    is (`CancellableExportProgress`)."""

    def cancel(self) -> None:
        pass


class CancellableExportProgress(CancellableWireExport, TransferProgress):
    """An export's progress: Core's export call reports to it and stops when it is cancelled.
    A frontend with no view of the counters uses it as it is; Textual's
    `WireExportProgressView` adds the counters and a cancel button."""


class Transfer(DeclaredFamily, affix="Request"):
    """One transfer kind the application offers. Members declare a title and a way to
    execute the operation. Each frontend's dialog for a kind is the member of its
    transfer-form family (`toad.client.transfer_forms.TransferForm.for_kind`) that
    composes it."""

    title: ClassVar[str]

    @abstractmethod
    async def execute(self, app: TransferHost, selected: CapturedSource) -> None: ...


class TransferRequest[Result: CliResult](Transfer):
    """A transfer carrying a typed Core call. One preparation lifetime runs `perform()`
    off the UI thread; failures surface through `app.show_error`, success through
    `completed()` (which both frontends get for free since `show_error` and `notify`
    are shared on `ClientApplication`)."""

    failure_title: ClassVar[str]
    cancelled_by: ClassVar[tuple[type[BaseException], ...]] = ()

    @abstractmethod
    def perform(self, access: CoordinationAccess, selected: CapturedSource,
                observer: TransferProgress) -> Result:
        """Run this transfer against the selected route's Core, reporting progress to observer."""

    async def execute(self, app: TransferHost, selected: CapturedSource) -> None:
        try:
            async with self.progress(app) as observer:
                try:
                    result = await app.preparation.run_thread(
                        self.perform, app.coordination_access, selected, observer)
                except asyncio.CancelledError:
                    observer.cancel()
                    raise
        except self.cancelled_by:
            self.cancelled(app)
            return
        except (OSError, ValueError) as error:
            app.show_error(error, self.failure_title)
            return
        self.completed(app, result)

    @asynccontextmanager
    async def progress(self, app: TransferHost) -> AsyncIterator[TransferProgress]:
        """Default progress sink: nothing to show, nothing to cancel."""
        yield TransferProgress()

    def cancelled(self, app: TransferHost) -> None:
        pass

    @abstractmethod
    def completed(self, app: TransferHost, result: Result) -> None: ...


class TransferHost(CommsHost):
    """The host contract both frontends supply so `TransferRequest.execute` runs without
    importing toolkit widgets. Textual's `ToadApp` and Qt's `QtToadApp` both satisfy it
    through their existing shared attrs plus one polymorphic opener per frontend."""

    coordination_access: CoordinationAccess
    preparation: PreparationRuntime
    events: core_events.CoreEventStream

    @asynccontextmanager
    async def export_progress(self) -> AsyncIterator[CancellableExportProgress]:
        """Where a running export reports. Without a view of its counters it is still
        cancellable: cancelling the transfer's task stops Core's export."""
        yield CancellableExportProgress()

    @abstractmethod
    def open_transfer(self, kind: type[Transfer]) -> None:
        """Open the frontend-specific dialog for `kind`; on submit, the frontend calls
        `start_transfer_task(request, selected)` with the composed request."""

    @abstractmethod
    def start_transfer_task(self, request: Transfer, selected: CapturedSource) -> None:
        """Run `request.execute(self, selected)` as a background task tagged by the
        request's declared name so repeated submissions supersede the previous one.
        Textual uses `run_worker(..., exclusive=True)`; Qt uses asyncio tasks keyed by
        the kind's declared name."""


@dataclass(frozen=True)
class WireExportRequest(TransferRequest[WireExportProvenance]):
    destination: Path
    format: WireExportFormat
    scope: WireExportScope
    limit: WireExportLimit

    failure_title = "Wire export failed"
    title = "Export wire history…"
    cancelled_by = (WireExportCancelled,)

    def perform(self, access: CoordinationAccess, selected: CapturedSource,
                observer: CancellableExportProgress) -> WireExportProvenance:
        """Core's host writes the export; its progress and cancel reach this observer."""
        return access.write(selected, access.observing(selected.root).core.call, CommsExportWireTool(
            destination=self.destination, format=self.format, scope=self.scope, limit=self.limit,
        ).observed_by(observer))

    def progress(self, app: TransferHost) -> AbstractAsyncContextManager[CancellableExportProgress]:
        """The host decides how a running export is shown (`TransferHost.export_progress`)."""
        return app.export_progress()

    def cancelled(self, app: TransferHost) -> None:
        app.notify("Wire export cancelled", title="Wire export")

    def completed(self, app: TransferHost, result: WireExportProvenance) -> None:
        app.notify(f"Exported {result.exported_messages} messages to {result.destination}", title="Wire export")


@dataclass(frozen=True)
class ThreadImportRequest(TransferRequest[ThreadImported]):
    source: Path
    harness: type[Harness]
    name: str
    session: ExpectedSession
    worktree: ImportDirectory

    failure_title = "Thread import failed"
    title = "Thread Import…"

    def perform(self, access: CoordinationAccess, selected: CapturedSource,
                observer: TransferProgress) -> ThreadImported:
        return access.write(selected, access.observing(selected.root).core.call, CommsImportThreadTool(
            source=self.source, harness=self.harness, name=self.name, session=self.session,
            worktree=self.worktree))

    def completed(self, app: TransferHost, result: ThreadImported) -> None:
        app.events.publish(core_events.ThreadRowStateChanged(frozenset((result.thread,))))
        app.notify(f"Imported @{result.thread} ({result.imported_messages} messages) as a stopped thread",
                   title="Thread Import")
