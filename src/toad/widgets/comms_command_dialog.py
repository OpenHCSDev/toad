"""Native parameter editing for one backend-declared operation."""
from __future__ import annotations

from agent_comms.cli_commands import TargetAction

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Select, Static, TextArea


class CommandDialog(ModalScreen[dict[str, str]]):
    DEFAULT_CSS = """
    CommandDialog { align: center middle; background: $background 40%; }
    CommandDialog #command-box { width: 68; max-width: 95%; height: 90%;
        background: $surface; border: solid $primary; padding: 1 2; }
    CommandDialog #command-body { height: 1fr; }
    CommandDialog #command-buttons { height: 3; align-horizontal: center; }
    CommandDialog #command-buttons Button { width: auto; min-width: 12; margin: 0 1; }
    CommandDialog #command-fields { height: auto; }
    CommandDialog #command-title { max-height: 3; text-overflow: ellipsis; }
    CommandDialog TextArea { height: 5; }
    """
    BINDINGS = [('escape', 'cancel', 'Cancel'), ('ctrl+enter', 'submit', 'Apply')]

    def __init__(self, definition: TargetAction, target: str):
        super().__init__()
        self.definition, self.target = definition, target

    def compose(self) -> ComposeResult:
        with Vertical(id='command-box'):
            yield Static(f"{self.definition.label} — {self.target}", markup=False, id='command-title')
            with VerticalScroll(id='command-body'):
                yield Static('', markup=False, id='command-confirmation')
                with Vertical(id='command-fields'):
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
            with Horizontal(id='command-buttons'):
                yield Button('Apply', id='command-apply', variant='primary')
                yield Button('Cancel', id='command-cancel')

    def on_mount(self):
        self.update_confirmation()
        fields = list(self.query('Input, TextArea, Select'))
        (fields[0] if fields else self.query_one('#command-cancel', Button)).focus()

    async def on_input_submitted(self, event: Input.Submitted):
        event.stop()
        await self.action_submit()

    async def on_button_pressed(self, event: Button.Pressed):
        event.stop()
        if event.button.id == 'command-apply':
            await self.action_submit()
        else:
            self.action_cancel()

    async def action_submit(self):
        if self.query_one('#command-apply', Button).disabled:
            return
        arguments = self.arguments()
        confirmed = self.query_one('#command-confirmed', Checkbox).value
        self.query_one('#command-apply', Button).disabled = True
        try:
            await self.app.preparation.run_thread(
                lambda: self.definition.edited(arguments).with_confirmation(confirmed))
        except (KeyError, ValueError, TypeError) as error:
            self.notify(str(error), severity='error')
            self.query_one('#command-apply', Button).disabled = False
            return
        if not self.is_attached:
            return
        if arguments != self.arguments():
            self.update_confirmation()
            return
        self.dismiss(arguments)

    def arguments(self):
        return {**{editor.name: editor.value for editor in self.query(Input)},
                **{editor.name: editor.text for editor in self.query(TextArea)},
                **{editor.name: str(editor.value) for editor in self.query(Select)}}

    def update_confirmation(self):
        confirmed = self.query_one('#command-confirmed', Checkbox)
        confirmed.value = False
        self.query_one('#command-apply', Button).disabled = True
        arguments = self.arguments()
        async def prepare():
            def read():
                try:
                    return self.definition.edited(arguments).confirmation
                except (KeyError, ValueError, TypeError):
                    return self.definition.confirmation
            confirmation = await self.app.preparation.run_thread(read)
            if not self.is_attached or arguments != self.arguments():
                return
            self.query_one('#command-confirmation', Static).update(confirmation)
            confirmed.display = bool(confirmation)
            self.query_one('#command-apply', Button).disabled = False
        self.run_worker(prepare, group='command-confirmation', exclusive=True)

    def on_select_changed(self, event: Select.Changed):
        self.update_confirmation()

    def on_input_changed(self, event: Input.Changed):
        self.update_confirmation()

    def on_text_area_changed(self, event: TextArea.Changed):
        self.update_confirmation()

    def action_cancel(self):
        self.dismiss(None)
