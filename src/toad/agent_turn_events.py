"""What a conversation does with its bound agent's turn events, for every frontend.

The agent publishes its response and thought text, its tool calls, its permission requests
and its slash commands on its event stream. Textual's `Conversation` and Qt's
`QtConversation` both receive them through the surface the agent attached
(`AgentConversation.agent_surface`) and answer them here, once: text goes to the shared
`LiveOutput`, a tool call to the agent's surface, a permission request to the view's
question. Each frontend answers only its own hooks: `consumed` (Textual stops the bubbling
message), `request_permissions` and `update_slash_commands`.
"""

from __future__ import annotations

from abc import abstractmethod

from metaclass_registry.mro_dispatch import MroDispatch, handles

from toad.core import events as core_events


class AgentTurnEvents(MroDispatch):
    """A conversation's handlers for its bound agent's turn events."""

    def consumed(self, message) -> None:
        """This view handled the publication; a frontend whose carrier bubbles stops it."""

    @abstractmethod
    def request_permissions(self, request) -> object:
        """Present one pending permission request through this view's question."""

    @abstractmethod
    def update_slash_commands(self) -> object:
        """Offer the agent's current commands in the composer."""

    @handles(core_events.Update)
    async def on_acp_agent_message(self, event: core_events.Update, message: core_events.Publication) -> None:
        self.consumed(message)
        if not self.agent_binding.matches_agent(message.publisher):
            return
        if self.turns.owner.busy:
            self.turns.describe("Writing response…")
        await self.output.append(event.stream, event.text)

    @handles(core_events.Thinking)
    async def on_acp_agent_thinking(self, event: core_events.Thinking, message: core_events.Publication) -> None:
        self.turns.describe("Thinking…")
        await self.output.append(event.stream, event.text)

    @handles(core_events.RequestPermission)
    async def on_acp_request_permission(self, event: core_events.RequestPermission, message: core_events.Publication) -> None:
        for request in message.publisher.permissions.pending:
            self.request_permissions(request)
        self.output.boundary()

    @handles(core_events.ToolCall)
    async def on_acp_tool_call_update(self, event: core_events.ToolCall, message: core_events.Publication) -> None:
        await message.publisher.controller.surface.present_tool(message, self)

    @handles(core_events.AvailableCommandsUpdate)
    async def on_acp_available_commands_update(
        self, event: core_events.AvailableCommandsUpdate, message: core_events.Publication
    ) -> None:
        self.update_slash_commands()
