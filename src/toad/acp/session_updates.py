"""Ordered ACP notification custody and declaration-owned external update effects."""
from __future__ import annotations

import asyncio
from abc import abstractmethod
from urllib.parse import quote

from agent_comms.acp_extension import decode_updates
from agent_comms.declared_family import DeclaredFamily
from toad import jsonrpc
from toad.acp import messages
from toad.core import events
from toad.acp.client_session import ClientRequestOwner, ClientSessionRequest
from toad.acp.context_measurement import ContextMeasurement
from toad.acp.sdk_boundary import decode_session_update
from agent_comms.mro_dispatch import MroDispatch, handles
from acp.schema import (UserMessageChunk, AgentMessageChunk, AgentThoughtChunk,
    ToolCallStart, ToolCallProgress, AgentPlanUpdate, AvailableCommandsUpdate,
    CurrentModeUpdate, ConfigOptionUpdate, SessionInfoUpdate, UsageUpdate, TextContentBlock)
from toad.plan import decode_plan


class SessionUpdateEffect(MroDispatch):
    """Effect registrations consume official SDK declarations, never raw shapes."""
    def __init__(self, agent, route):
        self.agent, self.route = agent, route

    def require_supported(self, update):
        if not any(self.handlers_for(update)):
            raise ValueError(f'ACP update capability is not supported: {type(update).__name__}')

    @handles(UserMessageChunk)
    def user(self, update):
        UserContentEffect(self.agent, self.route).dispatch_sync(update.content)

    @handles(AgentMessageChunk)
    def message(self, update):
        AgentContentEffect(self.agent, self.route).dispatch_sync(update.content)

    @handles(AgentThoughtChunk)
    def thought(self, update):
        ThoughtContentEffect(self.agent, self.route).dispatch_sync(update.content)

    @handles(ToolCallStart)
    def tool_start(self, update):
        self.agent.tools.begin(update)

    @handles(ToolCallProgress)
    def tool_progress(self, update):
        self.agent.tools.update(update)

    @handles(AgentPlanUpdate)
    def plan(self, update):
        self.agent.controller.publish_plan(decode_plan(update.entries))

    @handles(AvailableCommandsUpdate)
    def commands(self, update):
        self.agent.controller.publish_commands(update.available_commands)

    @handles(CurrentModeUpdate)
    def mode(self, update):
        self.agent.controller.update_mode(update.current_mode_id)

    @handles(ConfigOptionUpdate)
    def config(self, update):
        self.agent.configuration.receive(update.config_options)

    @handles(SessionInfoUpdate)
    def info(self, update):
        if 'title' in update.model_fields_set:
            self.agent.events.publish(events.SessionInfoUpdate(update.title))

    @handles(UsageUpdate)
    def usage(self, update):
        self.agent.context_measurement = ContextMeasurement.live(update.used, update.size, update.cost)
        self.agent.update_status_line()


class MessageContentEffect(MroDispatch):
    def __init__(self, agent, route):
        self.agent, self.route = agent, route

    @handles(TextContentBlock)
    def text(self, content):
        if content.text:
            self.publish(content)

    @abstractmethod
    def publish(self, content): ...


class UserContentEffect(MessageContentEffect):
    def publish(self, content):
        self.agent.post_message(messages.UserMessage(content.type, content.text))


class ThoughtContentEffect(MessageContentEffect):
    def publish(self, content):
        self.agent.events.publish(events.Thinking(content.type, content.text))


class AgentContentEffect(MessageContentEffect):
    def publish(self, content):
        text = content.text
        if text.startswith('[agent error]'):
            text += f'\n\n[Open ACP log]({quote(str(self.agent.presentation.log_path))})'
        from toad.widgets.agent_response import ResponseDelivery
        stream = self.agent.presentation.turns.owner.response_stream(ResponseDelivery.from_route(self.route))
        self.agent.post_message(messages.Update(content.type, text, stream, self.agent))


class SessionNotificationOwner(ClientRequestOwner):
    def __init__(self, agent):
        super().__init__(agent)
        self.lock = asyncio.Lock()

    @classmethod
    def resolve(cls, agent):
        return agent.updates

    @jsonrpc.expose('session/update', ordered=True)
    async def receive(self, sessionId: str, update: object, _meta: dict | None = None):
        authority = ClientSessionRequest(self.agent, self.agent.session_id)
        async with self.lock:
            if authority.retired or not authority.binding.admits_notification(sessionId):
                return
            validation = await self.agent.controller.validate(sessionId, update, _meta)
            if authority.retired:
                return
            validation.publish(self, sessionId, update, _meta)

    def accept(self, session_id, update, metadata=None):
        """Official SDK boundary for synchronous in-process protocol consumers."""
        authority = ClientSessionRequest(self.agent, self.agent.session_id)
        if authority.retired or not authority.binding.admits_notification(session_id):
            return
        try:
            accepted = decode_session_update(session_id, update, metadata)
        except (ValueError, TypeError) as error:
            self.reject(session_id, update, metadata, str(error))
            return
        self.publish(session_id, accepted)

    def reject(self, session_id, update, metadata, error):
        self.agent.log(
            f"[ACP rejected session/update] raw={{'sessionId': {session_id!r}, "
            f"'update': {update!r}, '_meta': {metadata!r}}}; validation={error}")
        self.agent.events.publish(events.RejectedSessionUpdate())

    def publish(self, session_id, update):
        metadata = update.update.field_meta
        consumer = self.agent.comms_consumer_class(self.agent, session_id)
        effect = SessionUpdateEffect(self.agent, consumer.route)
        try:
            effect.require_supported(update.update)
            facts = decode_updates(metadata)
        except (TypeError, ValueError) as error:
            self.reject(session_id, update, metadata, str(error))
            return
        for fact in facts:
            consumer.dispatch_sync(fact)
        effect.dispatch_sync(update.update)
