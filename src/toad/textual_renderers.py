"""Textual's renderers: work detached from a Textual consumer leaves its message pump and
Worker behind. The Qt frontend builds the plain renderers, so the phone, which ships no
Textual, never imports it to start a thread."""

from __future__ import annotations

from contextvars import ContextVar

from textual._context import active_message_pump
from textual.worker import active_worker

from toad.render_backend import PreparedRenderer, Renderer
from toad.render_processes import RenderProcessPool


class TextualOwners(Renderer):
    """A Textual consumer owns its message pump and Worker; detached work never borrows them."""

    def native_owners(self) -> tuple[ContextVar, ...]:
        return (active_message_pump, active_worker)


class TextualRenderProcessPool(TextualOwners, RenderProcessPool):
    """The render process pool, run under a Textual app."""


class TextualPreparedRenderer(TextualOwners, PreparedRenderer):
    """Shared preparation, run under a Textual app."""
