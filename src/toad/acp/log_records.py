"""Bounded physical log pages and declaration-owned diagnostic records."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import singledispatchmethod
from pathlib import Path
from typing import Literal

from acp import RequestError
from acp.schema import (
    AgentErrorMessage, AgentNotification, AgentRequest, AgentResponseMessage,
    ContentChunk, SessionNotification, TextContentBlock,
)
from pydantic import TypeAdapter, ValidationError
from agent_comms.acp_failure import ACPFailure, RequestFailure
from agent_comms.nominal.declared_family import DeclaredFamily


class LogSource(DeclaredFamily, affix="LogSource"):
    """Sender identity; both directions use the same JSON message schema."""


class AgentLogSource(LogSource):
    """A message received from the agent."""


class ClientLogSource(LogSource):
    """A message sent by the client."""


@dataclass(frozen=True)
class LogRecord(ABC):
    raw: str

    @property
    @abstractmethod
    def event(self) -> str: ...

    @property
    def diagnostic(self) -> str | None:
        return None

    def collect(self, records: list[LogRecord], diagnostics: list[str]) -> None:
        if diagnostics:
            records.append(DiagnosticLogRecord("".join(diagnostics)))
            diagnostics.clear()
        records.append(self)

    def continued_by(self, records: tuple[LogRecord, ...]) -> tuple[LogRecord, ...]:
        return (self, *records)

    def with_diagnostic(self, previous: DiagnosticLogRecord) -> tuple[LogRecord, ...]:
        return (previous, self)

    @classmethod
    def decode(cls, raw: str) -> LogRecord:
        """Decode the JSON written by AgentProcess for either sender."""
        tag, separator, body = raw.partition("] ")
        if not separator or not tag.startswith("["):
            return DiagnosticLogRecord(raw)
        try:
            source = LogSource.member_named(tag[1:])
        except ValueError:
            return DiagnosticLogRecord(raw)
        try:
            return LOG_MESSAGE.validate_json(body, strict=True).log_record(raw, source)
        except ValidationError as error:
            return UnparsedLogRecord(raw, str(error))


@dataclass(frozen=True)
class ProtocolLogRecord(LogRecord):
    source: type[LogSource]
    identity: str


@dataclass(frozen=True)
class ResponseLogRecord(ProtocolLogRecord):
    @property
    def event(self) -> str:
        return f"{self.source.declared_name} → response {self.identity}"


@dataclass(frozen=True)
class MethodLogRecord(ProtocolLogRecord):
    update: str

    @property
    def event(self) -> str:
        suffix = f" · {self.update}" if self.update else ""
        return f"{self.source.declared_name} → {self.identity}{suffix}"


@dataclass(frozen=True)
class FailureLogRecord(ProtocolLogRecord):
    observation: ACPFailure

    @property
    def event(self) -> str:
        code = f" · ACP code {self.observation.code}" if self.observation.code is not None else ""
        return f"{self.source.declared_name} → {self.identity} · {self.observation.title}{code}"

    @property
    def diagnostic(self) -> str:
        return f"{self.observation.title}\n{self.observation.description}\n\n{self.observation.action}"


class DiagnosticLogRecord(LogRecord):
    def collect(self, records: list[LogRecord], diagnostics: list[str]) -> None:
        diagnostics.append(self.raw)

    def continued_by(self, records: tuple[LogRecord, ...]) -> tuple[LogRecord, ...]:
        return (*records[0].with_diagnostic(self), *records[1:])

    def with_diagnostic(self, previous: DiagnosticLogRecord) -> tuple[LogRecord, ...]:
        return (DiagnosticLogRecord(previous.raw + self.raw),)

    @property
    def event(self) -> str:
        return self.raw.rstrip("\r\n")

    @property
    def diagnostic(self) -> str:
        return "Process diagnostics\n" + self.event


@dataclass(frozen=True)
class UnparsedLogRecord(LogRecord):
    reason: str

    @property
    def event(self) -> str:
        return self.reason + " — select Raw to inspect the original record"

    @property
    def diagnostic(self) -> str:
        return self.event + "\n" + self.raw.rstrip("\r\n")


class RecordFragment(LogRecord):
    @property
    def event(self) -> str:
        return "Long record continues on another page — select Raw or Earlier"

    @property
    def diagnostic(self) -> str:
        return self.event


class ErrorLogMessage(AgentErrorMessage):
    def log_record(self, raw: str, source: type[LogSource]) -> LogRecord:
        return FailureLogRecord(raw, source, str(self.id), RequestFailure.from_error(
            RequestError(**self.error.model_dump()),
        ).failure)


class SessionUpdateLogMessage(AgentNotification):
    method: Literal["session/update"]
    params: SessionNotification

    def log_record(self, raw: str, source: type[LogSource]) -> LogRecord:
        record = MethodLogRecord(raw, source, self.method, self.params.update.session_update)
        return SessionContentLog(record).render(self.params.update)


class MethodLogMessage(AgentNotification):
    def log_record(self, raw: str, source: type[LogSource]) -> LogRecord:
        return MethodLogRecord(raw, source, self.method, "")


class RequestLogMessage(AgentRequest, MethodLogMessage):
    """The SDK request fields share notification display behavior."""


class ResultLogMessage(AgentResponseMessage):
    def log_record(self, raw: str, source: type[LogSource]) -> LogRecord:
        return ResponseLogRecord(raw, source, str(self.id))


LOG_MESSAGE = TypeAdapter(
    ErrorLogMessage | SessionUpdateLogMessage | RequestLogMessage | MethodLogMessage | ResultLogMessage
)


class SessionContentLog:
    """Typed session content owns the textual agent-error convention."""

    def __init__(self, record: MethodLogRecord) -> None:
        self.record = record

    @singledispatchmethod
    def render(self, content: object) -> LogRecord:
        return self.record

    @render.register
    def chunk(self, update: ContentChunk) -> LogRecord:
        return self.render(update.content)

    @render.register
    def text(self, content: TextContentBlock) -> LogRecord:
        if content.text.startswith("[agent error] "):
            return FailureLogRecord(
                self.record.raw, self.record.source, self.record.identity,
                ACPFailure.from_detail(None, content.text.removeprefix("[agent error] ")),
            )
        return self.record


def decode_records(data: bytes, *, leading_fragment: bool, trailing_fragment: bool) -> tuple[LogRecord, ...]:
    lines = data.decode("utf-8", errors="replace").splitlines(keepends=True)
    records: list[LogRecord] = []
    diagnostics: list[str] = []
    for index, line in enumerate(lines):
        if (index == 0 and leading_fragment) or (index == len(lines) - 1 and trailing_fragment):
            record = RecordFragment(line)
        else:
            record = LogRecord.decode(line)
        record.collect(records, diagnostics)
    if diagnostics:
        records.append(DiagnosticLogRecord("".join(diagnostics)))
    return tuple(records)


@dataclass(frozen=True)
class LogPage:
    start: int
    end: int
    total: int
    raw: bytes
    records: tuple[LogRecord, ...]

    @classmethod
    def read(cls, path: Path, budget: int, before: int | None = None) -> LogPage:
        if budget < 1:
            raise ValueError("Log page budget must be positive")
        with path.open("rb") as stream:
            total = stream.seek(0, 2)
            end = total if before is None else min(max(0, before), total)
            start = max(0, end - budget)
            leading = False
            if start:
                stream.seek(start - 1)
                leading = stream.read(1) != b"\n"
            stream.seek(start)
            data = stream.read(end - start)
        if leading:
            boundary = data.find(b"\n")
            if 0 <= boundary < len(data) - 1:
                # The preceding complete record belongs to Earlier, whose end
                # now includes its newline. Nothing is discarded from the log.
                start += boundary + 1
                data = data[boundary + 1 :]
                leading = False
        trailing = end < total and bool(data) and not data.endswith(b"\n")
        records = decode_records(data, leading_fragment=leading, trailing_fragment=trailing)
        return cls(start, end, total, data, records)

    def extended(self, path: Path, budget: int) -> LogPage:
        """This page brought up to the end of the log.

        The same page when nothing was written; this page with the complete
        lines written after it; or the latest page when this one is not the
        log's end, the log was replaced, or the page outgrew twice the budget.
        """
        with path.open("rb") as stream:
            total = stream.seek(0, 2)
            if total == self.total:
                return self
            if self.end != self.total or total < self.end or total - self.start > 2 * budget:
                return self.read(path, budget)
            stream.seek(self.end)
            data = stream.read(total - self.end)
        # A line still being written is read once it is complete.
        data = data[: data.rfind(b"\n") + 1]
        if not data:
            return self
        records = decode_records(data, leading_fragment=False, trailing_fragment=False)
        earlier = self.records
        if earlier:
            records = earlier[-1].continued_by(records)
            earlier = earlier[:-1]
        end = self.end + len(data)
        return LogPage(self.start, end, end, self.raw + data, earlier + records)


class LogView(DeclaredFamily, affix="LogView"):
    # Where the latest record is drawn: at the end of the text, or at its start.
    newest_first = False

    @abstractmethod
    def render(self, page: LogPage) -> str: ...

    @classmethod
    def label(cls) -> str:
        return cls.declared_name.replace("_", " ").title()


class ErrorsLogView(LogView):
    newest_first = True

    def render(self, page: LogPage) -> str:
        errors = dict.fromkeys(record.diagnostic for record in reversed(page.records) if record.diagnostic)
        return "\n\n────────────────────\n\n".join(errors) or (
            "No decoded failures or process diagnostics on this page. "
            "Select Earlier, Events or Raw to inspect other records."
        )


class EventsLogView(LogView):
    def render(self, page: LogPage) -> str:
        return "\n\n".join(record.event for record in page.records)


class RawLogView(LogView):
    def render(self, page: LogPage) -> str:
        return page.raw.decode("utf-8", errors="replace")
