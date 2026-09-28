"""Decode diagnostic log records once; views consume their declared meaning."""

from abc import abstractmethod
import ast
from dataclasses import dataclass
import json
from pathlib import Path

from agent_comms.declared_family import DeclaredFamily


@dataclass(frozen=True)
class LogRecord:
    heading: str
    raw: str
    failure: bool = False

    @classmethod
    def read(cls, line: str) -> "LogRecord":
        direction, separator, body = line.partition("] ")
        if not separator or direction not in ("[agent", "[client"):
            return cls(line, line)
        try:
            # Toad's client logger writes Python repr; the agent writes JSON.
            value = json.loads(body) if direction == "[agent" else ast.literal_eval(body)
        except (ValueError, SyntaxError, RecursionError):
            return cls(line, line)
        if not isinstance(value, dict):
            return cls(line, line)
        raw = f"{direction}]\n{json.dumps(value, indent=2, ensure_ascii=False)}"
        if isinstance(error := value.get("error"), dict):
            data = error.get("data")
            detail = error.get("message", "ACP request failed")
            if isinstance(data, dict):
                detail = next((data[key] for key in ("details", "reason", "error")
                               if isinstance(data.get(key), str) and data[key].strip()), detail)
            return cls(f"{detail}\n\nACP code: {error.get('code', 'unspecified')}", raw, True)
        method = value.get("method")
        if isinstance(method, str):
            params = value.get("params")
            update = params.get("update") if isinstance(params, dict) else None
            if isinstance(update, dict):
                content = update.get("content")
                text = content.get("text") if isinstance(content, dict) else None
                if isinstance(text, str) and text.startswith("[agent error] "):
                    return cls(text.removeprefix("[agent error] "), raw, True)
                method += " · " + str(update.get("sessionUpdate", "update"))
            return cls(f"{direction[1:]} → {method}", raw)
        return cls(f"{direction[1:]} → response {value.get('id', '')}", raw)


@dataclass(frozen=True)
class LogPage:
    start: int
    end: int
    total: int
    records: tuple[LogRecord, ...]

    @classmethod
    def read(cls, path: Path, budget: int, before: int | None = None) -> "LogPage":
        with path.open("rb") as stream:
            total = stream.seek(0, 2)
            end = total if before is None else min(before, total)
            start = max(0, end - budget)
            stream.seek(start)
            data = stream.read(end - start)
        # Keep partial records visible as text; never load the whole log just
        # to find the beginning of an oversized protocol record.
        records = tuple(LogRecord.read(line) for line in data.decode("utf-8", errors="replace").splitlines())
        return cls(start, end, total, records)


class LogView(DeclaredFamily, affix="LogView"):
    @abstractmethod
    def render(self, records: tuple[LogRecord, ...]) -> str:
        """Return selectable diagnostic text for this view."""

    @classmethod
    def label(cls) -> str:
        return cls.declared_name.replace("_", " ").title()


class ErrorsLogView(LogView):
    def render(self, records: tuple[LogRecord, ...]) -> str:
        errors = dict.fromkeys(record.heading for record in reversed(records) if record.failure)
        return "\n\n────────────────────\n\n".join(errors) or "No parsed ACP errors in this page. Select Events or Raw to inspect other diagnostics."


class EventsLogView(LogView):
    def render(self, records: tuple[LogRecord, ...]) -> str:
        return "\n\n".join(record.heading for record in records)


class RawLogView(LogView):
    def render(self, records: tuple[LogRecord, ...]) -> str:
        return "\n\n".join(record.raw for record in records)
