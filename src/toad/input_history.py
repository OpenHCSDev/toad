"""Input history cases own durable paths, draft, cursor and navigation."""
from abc import abstractmethod
import hashlib
from pathlib import Path
from typing import Literal, cast

from agent_comms.declared_family import DeclaredFamily
from toad.history import History, HistoryEntry


class InputHistory(History, DeclaredFamily, affix="InputHistory"):
    def __init__(self, directory: Path, scope: str):
        super().__init__(self.history_path(directory, scope))
        self.index = 0

    @classmethod
    @abstractmethod
    def history_path(cls, directory: Path, scope: str) -> Path: ...

    @abstractmethod
    def skips(self, entry: HistoryEntry, reference: str) -> bool: ...

    def bound(self, directory: Path, scope: str):
        if self.path == self.history_path(directory, scope):
            return self
        return type(self)(directory, scope)

    def reset(self) -> None:
        self.current = None
        self.index = 0

    async def record(self, text: str) -> bool:
        self.reset()
        return await self.append(text)

    async def navigate(self, direction: Literal[-1, 1], draft: str) -> HistoryEntry:
        await self.open()
        if self.index == 0:
            self.current = draft
            reference = ""
        else:
            reference = (await self.get_entry(self.index)).input
        while True:
            next_index = min(0, max(-self.size, self.index + direction))
            if next_index == self.index:
                return await self.get_entry(self.index)
            self.index = next_index
            entry = await self.get_entry(self.index)
            if self.index in (0, -self.size) or not self.skips(entry, reference):
                return entry

    def present(self, prompt, entry: HistoryEntry) -> None:
        prompt.text = entry.input


class PromptInputHistory(InputHistory):
    @classmethod
    def history_path(cls, directory, scope):
        if not scope:
            return directory / "prompt_history.jsonl"
        digest = hashlib.sha256(scope.encode()).hexdigest()[:16]
        return directory / f"prompt_history-{digest}.jsonl"

    def skips(self, entry, reference):
        return False


class ShellInputHistory(InputHistory):
    @classmethod
    def history_path(cls, directory, scope):
        return directory / "shell_history.jsonl"

    def skips(self, entry, reference):
        return entry.input == reference

    def present(self, prompt, entry):
        super().present(prompt, entry)
        prompt.shell_mode = True


class InputHistories:
    """The same history/cursor owners survive optional view replacement."""
    def __init__(self, directory: Path, scope: str):
        self.directory, self.scope = directory, scope
        self.histories = self._create_histories()

    def _create_histories(self):
        return {member: member(self.directory, self.scope)
                for member in InputHistory.members_with(InputHistory)}

    def history[T: InputHistory](self, kind: type[T]) -> T:
        return cast(T, self.histories[kind])

    @property
    def prompt(self) -> PromptInputHistory:
        return self.history(PromptInputHistory)

    @property
    def shell(self) -> ShellInputHistory:
        return self.history(ShellInputHistory)

    def bind_scope(self, scope: str) -> None:
        if scope == self.scope:
            return
        self.scope = scope
        self.histories = {kind: history.bound(self.directory, scope)
                          for kind, history in self.histories.items()}

    def bind_project(self, directory: Path) -> None:
        self.directory = directory
        self.histories = self._create_histories()
