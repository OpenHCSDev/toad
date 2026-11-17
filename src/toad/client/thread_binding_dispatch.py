"""Toolkit-neutral dispatch for a conversation view's thread-presentation binding.

These four handlers used to live on `Conversation` in `src/toad/widgets/conversation.py`
(see the pre-split revisions). They never reached into Textual's Widget/DOMNode surface:
they call `consume_thread_presentation`, read `self.transcript` (a
`ConversationSources` field, lifted toolkit-neutral in PR #1902), check
`self.is_current_session`, and dispatch through `self.dispatch_sync` (a `MroDispatch`
method the concrete class already composes). The mixin pulls them into one place both
backends inherit, so Qt's `QtAcpSessionView` gets the same handler chain Textual's
`Conversation` does without copying it.

The mixin itself does not inherit `MroDispatch` — it stays composition-safe. The
concrete class is still responsible for having `MroDispatch` in its MRO; the
`@handles(...)` decorators here attach `__handled_classes__` as metadata, and the
dispatcher walks the MRO to pick them up.
"""

from __future__ import annotations

from agent_comms.registry.thread_presentation import NoThreadPresentation, ThreadPresentation
from metaclass_registry.mro_dispatch import handles

from toad.core import events as core_events
from toad.transcript_publication import ObservedSourcePublication


class ThreadBindingDispatch:
    """Handlers that bind one conversation view to its thread's observed presentations."""

    _unpublished_presentation: ThreadPresentation

    def thread_observed(self, event: core_events.ThreadRowsChanged) -> None:
        self.consume_thread_presentation()

    @handles(ThreadPresentation)
    def _publish_thread_source(self, presentation: ThreadPresentation) -> None:
        if not self.transcript.readable:
            return
        if self.is_current_session:
            self._unpublished_presentation = NoThreadPresentation()
            self.transcript.source_requests.request(
                ObservedSourcePublication, presentation
            )
        else:
            self._unpublished_presentation = presentation

    @handles(core_events.SessionSelected)
    async def _thread_view_selected(self, event: core_events.SessionSelected) -> None:
        if not self.is_current_session:
            return
        self.refresh_thread_status()
        self.dispatch_sync(self._unpublished_presentation)

    @handles(core_events.ObservedServiceChanged)
    async def _thread_route_observed(
        self, event: core_events.ObservedServiceChanged
    ) -> None:
        self.refresh_thread_status()
