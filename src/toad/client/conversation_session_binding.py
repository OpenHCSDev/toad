"""The session-binding contract a conversation view satisfies.

Declares the 9 methods a Conversation-shaped view must offer to bind, follow and
present one agent session's thread activity. Both Textual's `Conversation` widget
in `src/toad/widgets/conversation.py` and Qt's `QtAcpSessionView` structurally
satisfy this contract; a static type check against this Protocol replaces the
previous ad-hoc dependency on the Textual class itself.

The method bodies currently live only on the Textual Conversation widget because
each one reaches into ~18 widget-local attributes (`transcript`, `is_current_session`,
`refresh_thread_status`, `_update_model_info`, `goal_observation`, `feedback`,
`launch`, `call_later`, etc.) that each need their own toolkit-neutral extraction
before the bodies can move. Follow-up forks lift each dependency and migrate the
methods one at a time; this Protocol gives the interim type surface.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from toad.acp.comms_updates import ThreadRead


if TYPE_CHECKING:
    from toad.agent import AgentBase
    from toad.agent_binding import AgentConnection
    from agent_comms.registry.thread_presentation import ThreadPresentation
    from toad.core import events as core_events


@runtime_checkable
class ConversationSessionBinding(Protocol):
    """A conversation view that binds to and observes one agent session."""

    def bind_agent(self, agent: AgentConnection) -> None:
        """Attach this view to an agent connection as its presenter."""

    def apply_bound_agent(self, agent: AgentBase) -> None:
        """Project `agent`'s model/context/goal state onto the bound view."""

    def agent_connected(self, agent: AgentBase) -> None:
        """Flash a connection notice and record a usage milestone."""

    def arm_thread_read(self) -> None:
        """Capture the next presentation's turn token and client authority."""

    def consume_thread_presentation(self) -> None:
        """Consume this thread's one observed presentation."""

    def thread_observed(self, event: core_events.ThreadRowsChanged) -> None:
        """Handle an external coordination-observed thread row change."""

    def thread_presented(self, presentation: ThreadPresentation) -> None:
        """Project a newly-presented thread's transcript onto this view."""

    def _publish_thread_source(self, presentation: ThreadPresentation) -> None:
        """Route one observed thread presentation to the transcript source."""

    async def _thread_view_selected(self, event: core_events.SessionSelected) -> None:
        """Refresh status when this view's session becomes the selected one."""

    async def _thread_route_observed(
        self, event: core_events.ObservedServiceChanged
    ) -> None:
        """Refresh status when the observed-service routing changes."""


class ConversationThreadReadMixin:
    """Default `arm_thread_read` + `consume_thread_presentation` bodies, shared by both
    backends.

    Reaches for `self.agent_binding` (ObservedField on Qt, Textual `var` on the widget
    side — same `.thread_read()` call shape), `self.app` (DOMNode's on Textual, __init__
    attr on Qt), `self.status_thread()` + `self.thread_presented` (declared on the
    Protocol, implemented by each concrete view). No Textual Widget semantics.
    """

    _thread_read: ThreadRead = ThreadRead()
    """The source state the next observed presentation settles against."""

    def arm_thread_read(self) -> None:
        """Capture turn token and client authority for the next observed presentation."""
        self._thread_read = self.agent_binding.thread_read()

    def consume_thread_presentation(self) -> None:
        """Consume this thread's one observed presentation."""
        presentation = self.app.coordination_access.thread_status.open(
            self.status_thread().name
        ).presentation
        read = self._thread_read
        self.arm_thread_read()
        read.settle(presentation).present(self.thread_presented)
