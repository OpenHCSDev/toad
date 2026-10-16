"""Native parameter editing for one backend-declared operation."""
from __future__ import annotations

import asyncio

from agent_comms.cli_commands import TargetAction, TargetField
from agent_comms.comms import Comms

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from toad.screens.modal import ModalScreen
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

    def __init__(self, definition: TargetAction, target: str,
                 fields: tuple[TargetField, ...], comms: Comms):
        super().__init__()
        self.definition, self.target = definition, target
        self.fields, self.comms = fields, comms

    def compose(self) -> ComposeResult:
        with Vertical(id='command-box'):
            yield Static(f"{self.definition.label} — {self.target}", markup=False, id='command-title')
            with VerticalScroll(id='command-body'):
                yield Static('', markup=False, id='command-confirmation')
                with Vertical(id='command-fields'):
                    for parameter in self.fields:
                        key = parameter.name
                        yield Static(parameter.description, markup=False)
                        if (choices := parameter.choices) is not None:
                            value = parameter.editor_default
                            yield Select(choices,
                                         value=value if value in {item[1] for item in choices} else Select.BLANK,
                                         allow_blank=True, name=key,
                                         disabled=not choices,
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
                **{editor.name: '' if editor.value is Select.BLANK else str(editor.value)
                   for editor in self.query(Select)}}

    async def refresh_catalogs(self, arguments):
        requested = {item.name: arguments[item.name] for item in self.fields if item.catalog is not None}
        def unchanged():
            current = self.arguments()
            return all(current[name] == value for name, value in requested.items())
        self.query_one('#command-apply', Button).disabled = True
        try:
            fields = await self.app.preparation.run_thread(
                lambda: asyncio.run(self.definition.edited(arguments).prepare_fields(self.comms)))
        except (OSError, ValueError, RuntimeError) as error:
            if self.is_attached and unchanged():
                self.notify(str(error), title='Configuration choices', severity='error')
            return
        if not self.is_attached or not unchanged():
            return
        self.fields = fields
        with self.prevent(Select.Changed):
            for parameter in fields:
                if parameter.catalog is not None:
                    editor = self.query_one('#command-field-' + parameter.name.replace('_', '-'), Select)
                    choices = parameter.choices
                    editor.set_options(choices)
                    value = parameter.editor_default
                    editor.value = value if value in {item[1] for item in choices} else Select.BLANK
                    editor.disabled = not choices
        self.update_confirmation()

    def update_confirmation(self):
        confirmed = self.query_one('#command-confirmed', Checkbox)
        confirmed.value = False
        self.query_one('#command-apply', Button).disabled = True
        arguments = self.arguments()
        missing_choice = next((editor.name for editor in self.query(Select)
                               if editor.value is Select.BLANK), None)
        async def prepare():
            def read():
                try:
                    if missing_choice is not None:
                        raise ValueError(f'Choose {missing_choice.replace("_", " ")}')
                    return self.definition.edited(arguments).confirmation, True
                except (KeyError, ValueError, TypeError) as error:
                    return str(error), False
            confirmation, valid = await self.app.preparation.run_thread(read)
            if not self.is_attached or arguments != self.arguments():
                return
            self.query_one('#command-confirmation', Static).update(confirmation)
            confirmed.display = valid and bool(confirmation)
            self.query_one('#command-apply', Button).disabled = not valid or any(
                item.catalog is not None and item.editor_default != arguments[item.name]
                for item in self.fields)
        self.run_worker(prepare, group='command-confirmation', exclusive=True)

    def on_select_changed(self, event: Select.Changed):
        self.update_confirmation()
        if event.value is not Select.BLANK and any(
                item.name == event.select.name and item.catalog is not None
                and item.editor_default != event.value for item in self.fields):
            self.run_worker(self.refresh_catalogs(self.arguments()),
                            group='command-catalogs', exclusive=True)

    def on_input_changed(self, event: Input.Changed):
        self.update_confirmation()

    def on_text_area_changed(self, event: TextArea.Changed):
        self.update_confirmation()

    def action_cancel(self):
        self.dismiss(None)
