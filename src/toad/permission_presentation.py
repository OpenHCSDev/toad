"""Request-bound permission projections; the Agent retains the actual future."""
from __future__ import annotations

from abc import abstractmethod
from acp.schema import FileEditToolCallContent, ContentToolCallContent, TerminalToolCallContent
from dataclasses import dataclass
from functools import partial
from agent_comms.declared_family import DeclaredFamily


@dataclass
class PermissionPresentation(DeclaredFamily, affix="PermissionPresentation"):
    priority = 0
    title: str

    @classmethod
    def from_acp(cls, tool_call):
        """Decode the external ACP choice once, at request admission."""
        content = tool_call.content or []
        title = tool_call.title or ""
        for member in sorted(cls.members_with(cls), key=lambda member: member.priority, reverse=True):
            if (presentation := member.admit(tool_call.kind, title, content)) is not None:
                return presentation
        raise ValueError("No permission presentation admitted the ACP request")

    @classmethod
    @abstractmethod
    def admit(cls, kind, title, content): ...

    async def present(self, view, request):
        if (not request.pending or request.projected_on(view)
                or not request.controller.agent.controller.surface.owns(view)):
            return
        view.refresh_bindings()
        binding = request.controller.agent.controller.surface
        await self.show(view, request, binding)

    @abstractmethod
    async def show(self, view, request, binding): ...


class DiffPermissionPresentation(PermissionPresentation):
    def __init__(self, title, diffs):
        super().__init__(title)
        self.diffs = diffs

    @classmethod
    def admit(cls, kind, title, content):
        if kind != "edit" and not all(isinstance(item, FileEditToolCallContent) for item in content):
            return None
        records = [item for item in content if isinstance(item, FileEditToolCallContent)]
        diffs = [(item.path, item.path, item.old_text, item.new_text) for item in records]
        return cls(title, diffs) if diffs else None

    async def show(self, view, request, binding):
        from toad.screens.permissions import PermissionReview

        screen = PermissionReview(request, view, self.diffs, binding)
        app = view.app
        try:
            app.terminal_attention.require(screen)
            app.terminal_attention.notify(f"{view.agent_title} would like to write files",
                                          title="Permissions request", sound="question")
            request.watch(view, screen.retire)
            result = await app.push_screen_wait(screen, mode=view.screen.id)
            request.answer(binding, result)
        finally:
            app.terminal_attention.release(screen)
            if request.controller.agent.controller.surface is binding:
                view.refresh_bindings()


@dataclass
class InlinePermissionPresentation(PermissionPresentation):
    priority = -1
    parts: tuple[ContentToolCallContent | FileEditToolCallContent | TerminalToolCallContent, ...]

    @classmethod
    def admit(cls, kind, title, content):
        return cls(title, tuple(content))

    async def show(self, view, request, binding):
        from toad.widgets.acp_content import ACPToolCallContent
        from toad.tool_output import decode_content

        parts = tuple(preview for item in self.parts
                      if (preview := decode_content(item).permission_preview()) is not None)
        def answer(answer):
            if request.controller.agent.controller.surface is not binding:
                return
            request.answer(binding, answer)
            if not view.prompt.ask_queue:
                view.refresh_bindings()

        ask = view.ask(request.options, self.title,
                       partial(ACPToolCallContent, parts) if parts else None,
                       answer)

        def retire():
            if view.is_attached:
                view.prompt.remove_ask(ask)
                if view.prompt._ask is None:
                    view.refresh_bindings()

        request.watch(view, retire)
