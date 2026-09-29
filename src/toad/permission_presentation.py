"""Request-bound permission projections; the Agent retains the actual future."""
from __future__ import annotations

from abc import abstractmethod
from acp.schema import Diff
from functools import partial
from agent_comms.declared_family import DeclaredFamily
from toad import messages
from toad.widgets.acp_content import ACPToolCallContent


class PermissionPresentation(DeclaredFamily, affix="PermissionPresentation"):
    priority = 0

    def __init__(self, title):
        self.title = title

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
        from toad.screens.permissions import PermissionsScreen
        screen = PermissionsScreen(request.options, self.diffs,
                                   agent_name=view.agent_title or "The Agent")
        app = view.app
        app.terminal_alert()
        app.system_notify(f"{view.agent_title} would like to write files",
                          title="Permissions request", sound="question")

        def retire():
            if screen.is_attached:
                screen.dismiss(None)

        request.watch(view, retire)
        try:
            result = await app.push_screen_wait(screen, mode=view.screen.id)
            request.answer(view, result)
        finally:
            app.terminal_alert(False)
            if request.controller.agent.controller.surface.owns(view):
                view.post_message(messages.SessionUpdate(state="busy"))


class InlinePermissionPresentation(PermissionPresentation):
    priority = -1
    def __init__(self, title, content):
        super().__init__(title)
        self.content = content

    @classmethod
    def admit(cls, kind, title, content):
        return cls(title, content)

    async def show(self, view, request):
        def answer(answer):
            if not request.controller.agent.controller.surface.owns(view):
                return
            request.answer(view, answer)
            if not view.prompt.ask_queue:
                view.post_message(messages.SessionUpdate(state="busy"))

        ask = view.ask(request.options, self.title,
                       partial(ACPToolCallContent, self.content) if self.content else None,
                       answer)

        def retire():
            if view.is_attached:
                view.prompt.remove_ask(ask)
                if view.prompt._ask is None:
                    view.post_message(messages.SessionUpdate(state="busy"))

        request.watch(view, retire)
