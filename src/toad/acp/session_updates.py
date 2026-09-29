"""Ordered ACP notification custody and declaration-owned external update effects."""
from __future__ import annotations

import asyncio
from abc import abstractmethod
from urllib.parse import quote

from agent_comms.acp_extension import decode_updates
from agent_comms.declared_family import DeclaredFamily
from toad import jsonrpc
from toad.acp import messages
from toad.acp.client_session import ClientRequestOwner, ClientSessionRequest
from toad.acp.context_measurement import ContextMeasurement
from toad.acp.sdk_boundary import validate_session_update
from toad.plan import decode_plan


class SessionUpdateEffect(DeclaredFamily, affix="SessionUpdateEffect"):
    """The official SDK owns field validation; each declared case owns its effect."""
    def __init__(self, update):
        self.update = update

    @classmethod
    def from_wire(cls, update):
        return cls.decode(update['sessionUpdate'])(update)

    @abstractmethod
    def apply(self, agent, route): ...


class MessageChunkEffect(SessionUpdateEffect):
    def apply(self, agent, route):
        match self.update['content']:
            case {'type': kind, 'text': text}:
                self.publish(agent, route, kind, text)

    @abstractmethod
    def publish(self, agent, route, kind, text): ...


class UserMessageEffect(MessageChunkEffect, declared_name='user_message_chunk'):
    def publish(self, agent, route, kind, text):
        if text:
            agent.post_message(messages.UserMessage(kind, text))


class AgentMessageEffect(MessageChunkEffect, declared_name='agent_message_chunk'):
    def publish(self, agent, route, kind, text):
        if text:
            if kind == 'text' and text.startswith('[agent error]'):
                text += f'\n\n[Open ACP log]({quote(str(agent.presentation.log_path))})'
            agent.post_message(messages.Update(kind, text, route))


class AgentThoughtEffect(MessageChunkEffect, declared_name='agent_thought_chunk'):
    def publish(self, agent, route, kind, text):
        agent.post_message(messages.Thinking(kind, text))


class ToolCallEffect(SessionUpdateEffect, declared_name='tool_call'):
    def apply(self, agent, route):
        agent.tools.begin(self.update)


class ToolCallUpdateEffect(SessionUpdateEffect, declared_name='tool_call_update'):
    def apply(self, agent, route):
        agent.tools.update(self.update)


class PlanEffect(SessionUpdateEffect, declared_name='plan'):
    def apply(self, agent, route):
        agent.controller.publish_plan(decode_plan(self.update['entries']))


class CommandsEffect(SessionUpdateEffect, declared_name='available_commands_update'):
    def apply(self, agent, route):
        agent.controller.publish_commands(self.update['availableCommands'])


class ModeEffect(SessionUpdateEffect, declared_name='current_mode_update'):
    def apply(self, agent, route):
        mode = self.update['currentModeId']
        agent.controller.current_mode = mode
        agent.post_message(messages.ModeUpdate(mode))


class ConfigurationEffect(SessionUpdateEffect, declared_name='config_option_update'):
    def apply(self, agent, route):
        agent.configuration.receive({'configOptions': self.update['configOptions']})


class SessionInfoEffect(SessionUpdateEffect, declared_name='session_info_update'):
    def apply(self, agent, route):
        if 'title' in self.update:
            agent.post_message(messages.SessionInfoUpdate(self.update['title']))


class UsageEffect(SessionUpdateEffect, declared_name='usage_update'):
    def apply(self, agent, route):
        agent.context_measurement = ContextMeasurement.live(
            self.update['used'], self.update['size'], self.update.get('cost'))
        agent.update_status_line()


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
            if validation.error is not None:
                self.reject(sessionId, update, _meta, validation.error)
                return
            self.publish(sessionId, update)

    def accept(self, session_id, update, metadata=None):
        """Official SDK boundary for synchronous in-process protocol consumers."""
        from pydantic import ValidationError
        authority = ClientSessionRequest(self.agent, self.agent.session_id)
        if authority.retired or not authority.binding.admits_notification(session_id):
            return
        try:
            accepted = validate_session_update(session_id, update, metadata)
        except ValidationError as error:
            self.reject(session_id, update, metadata, str(error))
            return
        self.publish(session_id, accepted)

    def reject(self, session_id, update, metadata, error):
        self.agent.log(
            f"[ACP rejected session/update] raw={{'sessionId': {session_id!r}, "
            f"'update': {update!r}, '_meta': {metadata!r}}}; validation={error}")
        self.agent.post_message(messages.RejectedSessionUpdate())

    def publish(self, session_id, update):
        metadata = update.get('_meta')
        try:
            facts = decode_updates(metadata)
            effect = SessionUpdateEffect.from_wire(update)
        except (TypeError, ValueError) as error:
            self.reject(session_id, update, metadata, str(error))
            return
        consumer = self.agent.comms_consumer_class(self.agent, session_id)
        for fact in facts:
            consumer.dispatch_sync(fact)
        effect.apply(self.agent, consumer.route)
