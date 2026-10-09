"""Keep binding widgets mounted when focus changes leave their display unchanged."""

from dataclasses import dataclass, replace

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer as TextualFooter


@dataclass(frozen=True)
class FooterBinding:
    binding: Binding
    key_display: str
    enabled: bool
    tooltip: str


@dataclass(frozen=True)
class FooterState:
    bindings: tuple[FooterBinding, ...]
    command_palette: bool
    combine_groups: bool


class Footer(TextualFooter):
    _binding_state: FooterState | None = None

    def _current_binding_state(self, screen: Screen) -> FooterState:
        return FooterState(
            tuple(
                FooterBinding(replace(binding), self.app.get_key_display(binding), enabled, tooltip)
                for key, (_, binding, enabled, tooltip) in screen.active_bindings.items()
                if binding.show or key == self.app.COMMAND_PALETTE_BINDING
            ),
            self.show_command_palette and self.app.ENABLE_COMMAND_PALETTE,
            self.combine_groups,
        )

    def compose(self) -> ComposeResult:
        if self._bindings_ready:
            # A deferred rebuild may run after another focus transition. Keep
            # the memo aligned with what is composed, not only what was requested.
            self._binding_state = self._current_binding_state(self.screen)
        yield from super().compose()

    def bindings_changed(self, screen: Screen) -> None:
        if not self.is_attached or screen is not self.screen:
            return
        if not screen.app.app_focus:
            # Native Footer leaves its keys mounted while blurred. Retain their
            # state too, so restoring identical bindings doesn't rebuild them.
            super().bindings_changed(screen)
            return
        state = self._current_binding_state(screen)
        if state != self._binding_state or not self._bindings_ready:
            self._binding_state = state
            super().bindings_changed(screen)
