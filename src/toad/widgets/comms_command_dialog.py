"""Native parameter editing for one backend-declared operation."""
from __future__ import annotations

from agent_comms.cli_commands import TargetAction

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Select, Static, TextArea


class CommandDialog(ModalScreen[dict[str, str]]):
    DEFAULT_CSS = """
    CommandDialog { align: center middle; background: $background 40%; }
    CommandDialog #command-box { width: 68; height: auto; max-height: 90%;
        background: $surface; border: solid $primary; padding: 1 2; }
    CommandDialog #command-fields { height: auto; max-height: 24; }
    CommandDialog TextArea { height: 5; }
    """
    BINDINGS = [('escape', 'cancel', 'Cancel'), ('ctrl+enter', 'submit', 'Apply')]

    def __init__(self, definition: TargetAction, target: str):
        super().__init__()
        self.definition, self.target = definition, target

    def compose(self) -> ComposeResult:
        with Vertical(id='command-box'):
            yield Static(f"{self.definition.label} — {self.target}", markup=False)
            yield Static(self.definition.confirmation, markup=False, id='command-confirmation')
            with VerticalScroll(id='command-fields'):
                for parameter in self.definition.editable_fields:
                    key = parameter.name
                    yield Static(parameter.description, markup=False)
                    if parameter.choices:
                        yield Select(parameter.choices, value=parameter.editor_default,
                                     allow_blank=False, name=key,
                                     id='command-field-' + key.replace('_', '-'))
                    else:
                        widget = TextArea if parameter.multiline else Input
                        yield widget(parameter.editor_default, name=key,
                                     id='command-field-' + key.replace('_', '-'))
            yield Checkbox('I confirm this operation', id='command-confirmed')
            yield Button('Apply', id='command-apply', variant='primary')
            yield Button('Cancel', id='command-cancel')

    def on_mount(self):
        self.update_confirmation()
        fields = list(self.query('Input, TextArea, Select'))
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
        arguments = self.arguments()
        try:
            self.definition.edited(arguments).with_confirmation(
                self.query_one('#command-confirmed', Checkbox).value)
        except (KeyError, ValueError, TypeError) as error:
            self.notify(str(error), severity='error')
            return
        self.dismiss(arguments)

    def arguments(self):
        return {**{editor.name: editor.value for editor in self.query(Input)},
                **{editor.name: editor.text for editor in self.query(TextArea)},
                **{editor.name: str(editor.value) for editor in self.query(Select)}}

    def update_confirmation(self):
        try:
            confirmation = self.definition.edited(self.arguments()).confirmation()
        except (KeyError, ValueError, TypeError):
            confirmation = self.definition.confirmation
        self.query_one('#command-confirmation', Static).update(confirmation)
        confirmed = self.query_one('#command-confirmed', Checkbox)
        confirmed.display = bool(confirmation)
        confirmed.value = False

    def on_select_changed(self, event: Select.Changed):
        self.update_confirmation()

    def action_cancel(self):
        self.dismiss(None)
