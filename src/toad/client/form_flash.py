"""Toolkit-neutral form and list-row flash surface over ``formbridge.animation``.

Both Textual (``toad.forms.flash_surface.TextualFlashSurface``) and Qt
(``toad.qt.flash_surface.QtFlashSurface``) inherit ``FormFlashSurface``, sharing
``FlashCoordinator`` lifecycle, target registration, visibility admission, and
stale-key cleanup while supplying only native timer and paint hooks.
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Collection, Iterable, Mapping

from formbridge.animation.flash_coordinator import FlashCoordinator, FlashSurface


class FormFlashSurface(FlashSurface):
    """Shared ``FlashSurface`` owner for keyed widgets on any UI toolkit."""

    def __init__(self, coordinator: FlashCoordinator | None = None) -> None:
        self.coordinator = coordinator if coordinator is not None else FlashCoordinator()
        self._targets: dict[str, object] = {}
        self._painted_keys: set[str] = set()
        self.coordinator.register_surface(self)

    def bind_targets(self, targets: Mapping[str, object]) -> None:
        """Replace the key-to-target map tracked by this surface."""
        removed = self._painted_keys - targets.keys()
        for key in removed:
            target = self._targets.get(key)
            if target is not None:
                self.clear_target_flash(target)
        self._painted_keys.difference_update(removed)
        self._targets = dict(targets)

    def queue_flash(self, keys: Iterable[str]) -> None:
        """Start one synchronized flash cohort for ``keys`` on this surface's coordinator."""
        self.coordinator.queue_flash_batch(keys)

    def visible_recipients(self, keys: Collection[str]) -> set[tuple[int, str]]:
        recipients: set[tuple[int, str]] = set()
        for key in keys:
            target = self._targets.get(key)
            if target is not None and self.target_visible(target):
                recipients.add((id(target), key))
        return recipients

    def on_flash_frame(self, active_rgba: Mapping[str, tuple[int, int, int, int]]) -> None:
        finished = self._painted_keys - active_rgba.keys()
        for key in finished:
            target = self._targets.get(key)
            if target is not None:
                self.clear_target_flash(target)
        self._painted_keys.difference_update(finished)

        for key, rgba in active_rgba.items():
            target = self._targets.get(key)
            if target is None or not self.target_visible(target):
                continue
            self.paint_target_rgba(target, rgba)
            self._painted_keys.add(key)
            self.coordinator.acknowledge_painted((id(target), key), key, rgba[3])

    def dispose(self) -> None:
        """Clear all active tints and detach from the coordinator."""
        for key in tuple(self._painted_keys):
            target = self._targets.get(key)
            if target is not None:
                self.clear_target_flash(target)
        self._painted_keys.clear()
        self.coordinator.unregister_surface(self)
        self._targets.clear()

    @abstractmethod
    def target_visible(self, target: object) -> bool:
        """Return whether ``target`` is still alive and visible on screen."""

    @abstractmethod
    def paint_target_rgba(
        self, target: object, rgba: tuple[int, int, int, int]
    ) -> None:
        """Paint the current flash RGBA tint onto ``target``."""

    @abstractmethod
    def clear_target_flash(self, target: object) -> None:
        """Restore ``target`` to its non-flashing background."""
