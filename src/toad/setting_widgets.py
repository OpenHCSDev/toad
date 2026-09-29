"""Textual event boundaries bound directly to their preference declaration."""

from __future__ import annotations

from textual import on
from textual.screen import Screen
from textual.widgets import Checkbox, Input, Select, TextArea

from toad.settings import BoundSetting


class InputEditor(Input):
    def __init__(self, bound: BoundSetting, **kwargs) -> None:
        self.bound = bound
        super().__init__(
            bound.kind.display(bound.value), name=bound.key, classes="input", **kwargs
        )

    @on(Input.Blurred)
    @on(Input.Submitted)
    def commit(self, event: Input.Blurred | Input.Submitted) -> None:
        event.stop()
        self.commit_value(event.value)

    def commit_value(self, text: str) -> None:
        try:
            value = self.bound.kind.parse_text(text)
        except (ValueError, TypeError) as error:
            self.notify(str(error), title=self.bound.kind.title, severity="error")
            self.value = self.bound.kind.display(self.bound.value)
        else:
            self.bound.set(value)

    @classmethod
    def finish_focused(cls, screen: Screen) -> None:
        """Commit this family's focused edit before another queue saves it."""
        for editor in screen.query(cls):
            if editor.has_focus:
                editor.commit_value(editor.value)


class TextEditor(TextArea):
    def __init__(self, bound: BoundSetting[str]) -> None:
        self.bound = bound
        super().__init__(bound.value, name=bound.key, classes="input")

    @on(TextArea.Changed)
    def commit(self, event: TextArea.Changed) -> None:
        event.stop()
        self.bound.set(self.text)


class BooleanEditor(Checkbox):
    def __init__(self, bound: BoundSetting[bool]) -> None:
        self.bound = bound
        super().__init__(value=bound.value, name=bound.key, classes="input")

    @on(Checkbox.Changed)
    def commit(self, event: Checkbox.Changed) -> None:
        event.stop()
        self.bound.set(event.value)


class ChoiceEditor(Select):
    def __init__(self, bound: BoundSetting, family) -> None:
        self.bound = bound
        super().__init__(
            [(member.label(), member) for member in family.members_with(family)],
            value=bound.value,
            allow_blank=False,
            name=bound.key,
            classes="input",
        )

    @on(Select.Changed)
    def commit(self, event: Select.Changed) -> None:
        event.stop()
        if event.value is not Select.NULL:
            self.bound.set(event.value)
