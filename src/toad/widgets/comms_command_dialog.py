"""Native parameter editing for one backend-declared operation."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static


class CommandDialog(ModalScreen[dict[str, str]]):
    DEFAULT_CSS = """
    CommandDialog { align: center middle; background: $background 40%; }
    CommandDialog #command-box { width: 68; height: auto; max-height: 90%;
        background: $surface; border: solid $primary; padding: 1 2; }
    CommandDialog #command-fields { height: auto; max-height: 24; }
    """
    BINDINGS = [('escape', 'cancel', 'Cancel'), ('ctrl+enter', 'submit', 'Apply')]

    def __init__(self, definition, target):
        super().__init__()
        self.definition, self.target = definition, target

    def compose(self) -> ComposeResult:
        with Vertical(id='command-box'):
            yield Static(f"{self.definition['label']} — {self.target}", markup=False)
            if self.definition['confirmation']:
                yield Static(self.definition['confirmation'], markup=False)
            with VerticalScroll(id='command-fields'):
                for key, parameter in self.definition['parameters']['properties'].items():
                    yield Static(parameter['description'], markup=False)
                    yield Input(parameter['editor_default'], name=key,
                                id='command-field-' + key.replace('_', '-'))
            yield Button('Apply', id='command-apply', variant='primary')
            yield Button('Cancel', id='command-cancel')

    def on_mount(self):
        fields = list(self.query(Input))
        (fields[0] if fields else self.query_one('#command-cancel', Button)).focus()

    def on_input_submitted(self, event: Input.Submitted):
        event.stop()
        self.action_submit()

    def on_button_pressed(self, event: Button.Pressed):
        event.stop()
        if event.button.id == 'command-apply':
            self.action_submit()
        else:
            self.action_cancel()

    def action_submit(self):
        self.dismiss({editor.name: editor.value for editor in self.query(Input)})

    def action_cancel(self):
        self.dismiss(None)
