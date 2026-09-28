"""Bounded physical log pages and declaration-owned diagnostic records."""

from __future__ import annotations

from abc import ABC, abstractmethod
import ast
from dataclasses import dataclass
import json
from pathlib import Path

from agent_comms.acp_failure import ACPFailure
from agent_comms.declared_family import DeclaredFamily


class LogSource(DeclaredFamily, affix="LogSource"):
    @classmethod
    @abstractmethod
    def parse(cls, body: str) -> object: ...


class AgentLogSource(LogSource):
    @classmethod
    def parse(cls, body: str) -> object:
        return json.loads(body)


class ClientLogSource(LogSource):
    @classmethod
    def parse(cls, body: str) -> object:
        return ast.literal_eval(body)


@dataclass(frozen=True)
class LogRecord(ABC):
    raw: str

    @property
    @abstractmethod
    def event(self) -> str: ...

    @property
    def diagnostic(self) -> str | None:
        return None

    @classmethod
    def decode(cls, raw: str) -> LogRecord:
        """The agent JSON and client repr are distinct current logger sources."""
        tag, separator, body = raw.partition("] ")
        if not separator or not tag.startswith("["):
            return DiagnosticLogRecord(raw)
        try:
            source = LogSource.decode(tag[1:])
        except ValueError:
            return DiagnosticLogRecord(raw)
        try:
            value = source.parse(body)
        except (ValueError, SyntaxError, RecursionError) as error:
            return UnparsedLogRecord(raw, f"Unable to decode {source.declared_name} record: {error}")
        if not isinstance(value, dict):
            return UnparsedLogRecord(raw, "Protocol record is not an object")
        if isinstance(error := value.get("error"), dict):
            code = error.get("code")
            message = error.get("message")
            failure = ACPFailure.from_error(
                code if isinstance(code, int) and not isinstance(code, bool) else None,
                message if isinstance(message, str) else "ACP request failed",
                error.get("data"),
            )
            return FailureLogRecord(raw, source, str(value.get("id", "")), failure)
        if isinstance(method := value.get("method"), str):
            params = value.get("params")
            update = params.get("update") if isinstance(params, dict) else None
            update_name = ""
            if isinstance(update, dict):
                content = update.get("content")
                text = content.get("text") if isinstance(content, dict) else None
                if isinstance(text, str) and text.startswith("[agent error] "):
                    failure = ACPFailure.from_error(None, text.removeprefix("[agent error] "))
                    return FailureLogRecord(raw, source, method, failure)
                update_name = str(update.get("sessionUpdate", "update"))
            return MethodLogRecord(raw, source, method, update_name)
        return ResponseLogRecord(raw, source, str(value.get("id", "")))


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


def decode_records(data: bytes, *, leading_fragment: bool, trailing_fragment: bool) -> tuple[LogRecord, ...]:
    lines = data.decode("utf-8", errors="replace").splitlines(keepends=True)
    records: list[LogRecord] = []
    diagnostics: list[str] = []
    for index, line in enumerate(lines):
        if (index == 0 and leading_fragment) or (index == len(lines) - 1 and trailing_fragment):
            record = RecordFragment(line)
        else:
            record = LogRecord.decode(line)
        # Adjacent process stderr/traceback lines are one physical diagnostic.
        # This is the decode boundary; presentation never switches on cases.
        if isinstance(record, DiagnosticLogRecord):
            diagnostics.append(line)
            continue
        if diagnostics:
            records.append(DiagnosticLogRecord("".join(diagnostics)))
            diagnostics.clear()
        records.append(record)
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


class LogView(DeclaredFamily, affix="LogView"):
    @abstractmethod
    def render(self, page: LogPage) -> str: ...

    @classmethod
    def label(cls) -> str:
        return cls.declared_name.replace("_", " ").title()


class ErrorsLogView(LogView):
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
