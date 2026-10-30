"""Uncommitted member transactions, independent of a backend's member types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import make_dataclass
from typing import ClassVar

from formbridge.forms.declared_fields import DeclaredField
from objectstate import ObjectState
from textual.screen import ModalScreen


class MemberDraft[Selection = object](ABC):
    """Uncommitted inputs; the containing field remains the committed value."""

    state: ObjectState
    selection: Selection
    refusal: ClassVar[type[Exception]]

    @abstractmethod
    def complete(self) -> object: ...


class MemberNotChosen(ValueError):
    """The transaction has not selected an original declaration yet."""


class UnchosenMemberDraft[Selection = object](MemberDraft[Selection]):
    refusal = MemberNotChosen

    def __init__(self, selection: Selection) -> None:
        self.selection = selection
        self.state = ObjectState(make_dataclass('UnchosenMember', [])())

    def complete(self) -> object:
        raise MemberNotChosen('Choose a member')


class UnionMembers[Selection = object](ABC):
    """Backend declarations supply choices and construct a pending member."""

    @abstractmethod
    def choices(self) -> tuple[Selection, ...]: ...

    @abstractmethod
    def label(self, choice: Selection) -> str: ...

    @abstractmethod
    def selected(self, value: object) -> Selection: ...

    @abstractmethod
    def draft(self, choice: Selection, value: object) -> MemberDraft[Selection]: ...

    @abstractmethod
    def dialog(self, field: DeclaredField) -> ModalScreen[None]: ...
