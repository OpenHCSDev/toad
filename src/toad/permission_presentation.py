"""Decoded permission content; the Agent retains the actual request future."""
from __future__ import annotations

from abc import abstractmethod
from acp.schema import FileEditToolCallContent, ContentToolCallContent, TerminalToolCallContent
from dataclasses import dataclass
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

@dataclass
class InlinePermissionPresentation(PermissionPresentation):
    priority = -1
    parts: tuple[ContentToolCallContent | FileEditToolCallContent | TerminalToolCallContent, ...]

    @classmethod
    def admit(cls, kind, title, content):
        return cls(title, tuple(content))
