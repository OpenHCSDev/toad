"""One owner for logical open order and visited-tab navigation."""

from collections.abc import Callable, Collection, Mapping

from textual.message_pump import MessagePump
from textual.signal import Signal


class TabOrder:
    def __init__(
        self, owner: MessagePump, focus: Callable[[str, int | None], object]
    ) -> None:
        self._open: list[str] = []
        self._visits: list[str] = []
        self._cursor = -1
        self._focus = focus
        self.changed: Signal[None] = Signal(owner, "tab-history-changed")

    def __contains__(self, mode: str | None) -> bool:
        return mode in self._open

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._open)

    def open(self, mode: str, *, after: str | None = None) -> None:
        if mode in self:
            return
        insertion = self._open.index(after) + 1 if after in self else len(self._open)
        self._open.insert(insertion, mode)

    def project[T](self, values: Mapping[str, T]) -> tuple[T, ...]:
        return tuple(values[mode] for mode in self._open if mode in values)

    def previous(
        self,
        current: str,
        *,
        eligible: Collection[str] | None = None,
        excluded: Collection[str] = (),
    ) -> str:
        candidates = [
            mode
            for mode in self._open
            if mode not in excluded
            and mode != current
            and (eligible is None or mode in eligible)
        ]
        preceding = (
            self._open[: self._open.index(current)] if current in self else self._open
        )
        return next(
            (mode for mode in reversed(preceding) if mode in candidates),
            candidates[0] if candidates else "store",
        )

    def history_target(self, direction: int) -> tuple[int, str] | None:
        index = self._cursor + direction
        if 0 <= index < len(self._visits):
            return index, self._visits[index]
        return None

    def navigate(self, direction: int) -> None:
        if target := self.history_target(direction):
            index, mode = target
            if mode == self._visits[self._cursor]:
                self.record_visit(mode, index)
            else:
                self._focus(mode, index)

    def record_visit(self, mode: str, history_index: int | None = None) -> None:
        if mode not in self:
            return
        if (
            history_index is not None
            and 0 <= history_index < len(self._visits)
            and self._visits[history_index] == mode
        ):
            self._cursor = history_index
        else:
            del self._visits[self._cursor + 1 :]
            self._visits.append(mode)
            self._cursor = len(self._visits) - 1
        self.changed.publish(None)

    def close(self, modes: Collection[str]) -> None:
        self._open[:] = [mode for mode in self._open if mode not in modes]
        retained = []
        cursor = -1
        for index, mode in enumerate(self._visits):
            if mode in self:
                retained.append(mode)
                if index <= self._cursor:
                    cursor = len(retained) - 1
        if retained != self._visits:
            self._visits, self._cursor = retained, cursor
            self.changed.publish(None)
