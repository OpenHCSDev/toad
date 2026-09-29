"""Request-bound permission projections; the Agent retains the actual future."""
from __future__ import annotations

from abc import abstractmethod
from acp.schema import Diff
from dataclasses import dataclass
from functools import partial
from toad.screens.permissions import PermissionReview
from agent_comms.declared_family import DeclaredFamily
from toad import messages
from toad.widgets.acp_content import ACPToolCallContent
from toad.tool_output import ToolOutputPart, decode_content


@dataclass
class PermissionPresentation(DeclaredFamily, affix="PermissionPresentation"):
    priority = 0
    title: str

    @classmethod
    def from_acp(cls, tool_call):
        """Decode the external ACP choice once, at request admission."""
        content = tool_call.get("content") or []
        title = tool_call.get("title") or ""
        for member in sorted(cls.members_with(cls), key=lambda member: member.priority, reverse=True):
            if (presentation := member.admit(tool_call.get("kind"), title, content)) is not None:
                return presentation
        raise ValueError("No permission presentation admitted the ACP request")

    @classmethod
    @abstractmethod
    def admit(cls, kind, title, content): ...

    async def present(self, view, request):
        if not request.pending or not request.controller.agent.controller.surface.owns(view):
            return
        view.post_message(messages.SessionUpdate(state="asking"))
        await self.show(view, request)

    @abstractmethod
    async def show(self, view, request): ...


class DiffPermissionPresentation(PermissionPresentation):
    def __init__(self, title, diffs):
        super().__init__(title)
        self.diffs = diffs

    @classmethod
    def admit(cls, kind, title, content):
        if kind != "edit" and not all(item.get("type") == "diff" for item in content):
            return None
        records = [Diff.model_validate(item) for item in content if item.get("type") == "diff"]
        diffs = [(item.path, item.path, item.old_text, item.new_text) for item in records]
        return cls(title, diffs) if diffs else None

    async def show(self, view, request):
        screen = PermissionReview(request, view, self.diffs)
        app = view.app
        try:
            app.terminal_attention.require(screen)
            app.terminal_attention.notify(f"{view.agent_title} would like to write files",
                                          title="Permissions request", sound="question")
            request.watch(view, screen.retire)
            result = await app.push_screen_wait(screen, mode=view.screen.id)
            request.answer(view, result)
        finally:
            app.terminal_attention.release(screen)
            if request.controller.agent.controller.surface.owns(view):
                view.post_message(messages.SessionUpdate(state="busy"))


@dataclass
class InlinePermissionPresentation(PermissionPresentation):
    priority = -1
    parts: tuple[ToolOutputPart, ...]

    @classmethod
    def admit(cls, kind, title, content):
        return cls(title, tuple(preview for item in content
                               if (preview := decode_content(item).permission_preview()) is not None))

    async def show(self, view, request):
        def answer(answer):
            if not request.controller.agent.controller.surface.owns(view):
                return
            request.answer(view, answer)
            if not view.prompt.ask_queue:
                view.post_message(messages.SessionUpdate(state="busy"))

        ask = view.ask(request.options, self.title,
                       partial(ACPToolCallContent, self.parts) if self.parts else None,
                       answer)

        def retire():
            if view.is_attached:
                view.prompt.remove_ask(ask)
                if view.prompt._ask is None:
                    view.post_message(messages.SessionUpdate(state="busy"))

        request.watch(view, retire)
