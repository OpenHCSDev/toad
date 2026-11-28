"""Toolkit-neutral Vimium click hints: intent, targets, progressive key session, and declared actions.

Both Textual (`Screen` / `ModalScreen` / `WorkspaceFrame`) and Qt (`QtToadApp` / `QtHintOverlay`)
share these declarations:

- `HintIntent` (`PrimaryHint`, `ContextHint`) dispatches polymorphically to `HintTargetSource`
  without button-enum or `if` switches.
- `HintSessionState(HintKeyAssignment)` owns home-row-first key assignment, prefix narrowing,
  Backspace/Escape handling, and polymorphic `HintStep` results (`HintNarrowed`, `HintMatched`,
  `HintDismissed`).
- `OpenHintsAction` (`f` in `VimMode`) and `OpenContextHintsAction` (`ctrl+f` in `VimMode`) live
  here once so both frontends share the exact same keymap declarations and `saved_key` names.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from typing import ClassVar

from formbridge.hint_keys import HintKeyAssignment, HintLabelStyle, NextLetterHints
from textual.document._editing import VimMode

from toad.widget_actions import WidgetAction


class HintTarget(ABC):
    """One exposed clickable target on screen, located in host-window coordinates."""

    x: int
    y: int

    @abstractmethod
    def available(self) -> bool:
        """Whether this target is still mounted, visible, and enabled."""

    @abstractmethod
    def activate(self) -> object:
        """Invoke the target's original click or context-menu action."""


class HintTargetSource:
    """A UI control that exposes primary and/or contextual hint targets polymorphically."""

    def primary_hint_targets(self, host: object) -> Iterable[HintTarget]:
        return ()

    def context_hint_targets(self, host: object) -> Iterable[HintTarget]:
        return ()


class HintIntent(ABC):
    """Which click effect a hint overlay exposes — dispatched polymorphically to each target source."""

    description: ClassVar[str]

    @abstractmethod
    def targets_of(self, source: HintTargetSource, host: object) -> Iterable[HintTarget]: ...


class PrimaryHint(HintIntent):
    """Left-click / primary activation hints."""

    description = "Left-click hints"

    def targets_of(self, source: HintTargetSource, host: object) -> Iterable[HintTarget]:
        return source.primary_hint_targets(host)


class ContextHint(HintIntent):
    """Right-click / context-menu hints."""

    description = "Right-click hints"

    def targets_of(self, source: HintTargetSource, host: object) -> Iterable[HintTarget]:
        return source.context_hint_targets(host)


@dataclass(frozen=True)
class HintEntry:
    """One assigned home-row key paired with its live target."""

    key: str
    target: HintTarget


class HintStep(ABC):
    """Outcome of feeding one key into `HintSessionState`, applied polymorphically by the overlay."""

    @abstractmethod
    def apply(self, overlay: object) -> None: ...


class HintNarrowed(HintStep):
    """The typed prefix still matches one or more targets; repaint the narrowed labels."""

    def apply(self, overlay: object) -> None:
        overlay.hints_narrowed()


@dataclass(frozen=True)
class HintMatched(HintStep):
    """The typed key uniquely matched one live target; dismiss and activate it."""

    target: HintTarget

    def apply(self, overlay: object) -> None:
        overlay.hint_matched(self.target)


class HintDismissed(HintStep):
    """No target matches (or the user cancelled); dismiss and restore original focus."""

    def apply(self, overlay: object) -> None:
        overlay.dismiss_hints()


class HintSessionState(HintKeyAssignment):
    """Toolkit-neutral progressive hint matcher over reading-order sorted targets."""

    entries: tuple[HintEntry, ...] = ()
    prefix: str = ""
    label_style: type[HintLabelStyle] = NextLetterHints

    def begin_session(
        self,
        targets: Iterable[HintTarget],
        label_style: type[HintLabelStyle] = NextLetterHints,
    ) -> tuple[HintEntry, ...]:
        ordered = sorted(
            (target for target in targets if target.available()),
            key=lambda target: (target.y, target.x),
        )
        width = self.label_width(len(ordered)) if ordered else 1
        self.entries = tuple(
            HintEntry(self.label(index, width), target)
            for index, target in enumerate(ordered)
        )
        self.prefix = ""
        self.label_style = label_style
        return self.entries

    def clear_session(self) -> None:
        self.entries = ()
        self.prefix = ""

    def visible_entries(self) -> tuple[tuple[HintEntry, str, int], ...]:
        """Each matching live entry paired with `(shown_text, typed_prefix_count)`."""
        result: list[tuple[HintEntry, str, int]] = []
        for entry in self.entries:
            if entry.key.startswith(self.prefix) and entry.target.available():
                shown, typed = self.label_style.shown(entry.key, self.prefix)
                result.append((entry, shown, typed))
        return tuple(result)

    def feed_character(self, character: str) -> HintStep:
        """Advance the prefix by one typed character and return the next polymorphic step."""
        ch = character.lower()
        if ch not in self.alphabet:
            return HintDismissed()
        self.prefix += ch
        remaining = [
            entry
            for entry in self.entries
            if entry.key.startswith(self.prefix) and entry.target.available()
        ]
        if not remaining:
            return HintDismissed()
        if len(remaining) == 1 and remaining[0].key == self.prefix:
            return HintMatched(remaining[0].target)
        return HintNarrowed()

    def backspace(self) -> HintStep:
        """Step back one character in the typed prefix, or dismiss if already empty."""
        if not self.prefix:
            return HintDismissed()
        self.prefix = self.prefix[:-1]
        return HintNarrowed()


class HintHostSurface:
    """Shared host contract for screens/windows that can display Vimium UI hints."""

    def hints_available(self) -> bool:
        """False while a text editor or search field owns bare-letter keystrokes."""
        return True

    def action_show_hints(self) -> object:
        raise NotImplementedError

    def action_show_context_hints(self) -> object:
        raise NotImplementedError


class HintTargetAction(WidgetAction, declared_name=None):
    """Hint actions available only when the workspace exposes hint targets."""

    def available(self, context: HintHostSurface) -> bool:
        return context.hints_available()


class OpenHintsAction(HintTargetAction):
    """Show left-click hints."""

    title = PrimaryHint.description
    keys = {VimMode: ("f",)}

    def apply(self, context: HintHostSurface) -> object:
        return context.action_show_hints()


class OpenContextHintsAction(HintTargetAction):
    """Show right-click hints."""

    title = ContextHint.description
    keys = {VimMode: ("ctrl+f",)}

    def apply(self, context: HintHostSurface) -> object:
        return context.action_show_context_hints()
