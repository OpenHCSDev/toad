"""The shared form edits one backend-declared operation and its catalogs."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, make_dataclass
from typing import Annotated

from agent_comms.cli_commands import ChoiceTargetField, TargetAction, TargetField
from agent_comms.config_options import ModelConfigOption
from agent_comms.login import run_login
from agent_comms.native_pi import NativePiUnavailable
from objectstate import ObjectState
from python_introspect import AnnotationChoices, FieldLabel
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Checkbox, Static
from toad.forms.editors import ValueEditor
from toad.forms.form_view import InlineFormView
from toad.forms.kinds import Multiline
from toad.screens.modal import ModalScreen
from toad.widgets.model_switcher import ModelSelection


@dataclass(eq=False)
class PreparedChoices(AnnotationChoices):
    """The catalog last prepared for a draft, not another copy of its value."""
    parameter: ChoiceTargetField

    def choices(self):
        return ('', *(value for _, value in self.parameter.choices))

    def label(self, choice):
        return next((label for label, value in self.parameter.choices if value == choice), 'Choose…')


ValueEditor.shown_by[PreparedChoices] = lambda field: ValueEditor.showing(
    (*field.metadata(PreparedChoices).parameter.editor_declarations, AnnotationChoices)
)(field)


class CatalogField(ValueEditor, Button):
    """The shared model selector edits the form's canonical draft value."""
    shows = (ModelConfigOption,)

    def bind_control(self):
        self.paint()

    def paint(self):
        self.label = next((choice.name for choice in self.field.metadata(PreparedChoices).parameter.options
                           if choice.value == self.field.value), 'Choose / connect a provider…')

    def on_button_pressed(self, event: Button.Pressed):
        event.stop()
        self.choose()

    @work(exclusive=True)
    async def choose(self):
        value = await self.app.push_screen_wait(CatalogChoiceDialog(self))
        if value is not None and self.is_attached:
            self.send(value)


class CatalogFieldSelection(ModelSelection):
    def __init__(self, editor: CatalogField):
        self.editor = editor
        super().__init__()

    @property
    def choices(self):
        return self.editor.field.metadata(PreparedChoices).parameter.options

    @property
    def current(self):
        return self.editor.field.value

    @property
    def selection_active(self):
        return self.is_attached

    def compose(self):
        yield from self.compose_content()

    def on_mount(self):
        self.focus_content(False)

    def select_model(self, model_id: str):
        self.screen.dismiss(model_id)

    def action_dismiss(self):
        self.screen.dismiss(None)

    @work(exclusive=True)
    async def connect_provider(self):
        command = self.editor.query_ancestor(CommandDialog)
        try:
            with self.app.suspend():
                result = await asyncio.to_thread(run_login)
        except OSError as error:
            self.notify(str(error), title='Provider login', severity='error')
            return
        if result == 0 and self.is_attached:
            await command.refresh_catalogs(command.arguments())
            self.configuration_changed()
        elif self.is_attached:
            self.notify(f'Provider login exited with status {result}', severity='error')
        if self.is_attached:
            self.search_input.focus()


class CatalogChoiceDialog(ModalScreen[str]):
    DEFAULT_CSS = 'CatalogChoiceDialog { align: center middle; background: $background 40%; }'

    def __init__(self, editor: CatalogField):
        super().__init__()
        self.editor = editor

    def compose(self):
        yield CatalogFieldSelection(self.editor)


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

    def __init__(self, definition: TargetAction, target: str, fields: tuple[TargetField, ...]):
        super().__init__()
        self.definition, self.target = definition, target
        self.choices = {}
        declarations = []
        for parameter in fields:
            hints = [FieldLabel(parameter.description)]
            hints.extend(parameter.editor_hints(
                lambda item: self.choices.setdefault(item.name, PreparedChoices(item))))
            if parameter.multiline:
                hints.append(Multiline())
            declarations.append((parameter.name, Annotated[str, *hints],
                                 field(default=parameter.editor_default)))
        self.state = ObjectState(make_dataclass('CommandDraft', declarations)())
        self.form = InlineFormView(self.state)
        self.form.id = 'command-fields'

    def compose(self) -> ComposeResult:
        with Vertical(id='command-box'):
            yield Static(f"{self.definition.label} — {self.target}", markup=False, id='command-title')
            with VerticalScroll(id='command-body'):
                yield Static('', markup=False, id='command-confirmation')
                yield self.form
            yield Checkbox('I confirm this operation', id='command-confirmed')
            with Horizontal(id='command-buttons'):
                yield Button('Apply', id='command-apply', variant='primary')
                yield Button('Cancel', id='command-cancel')

    def on_mount(self):
        self.state.on_resolved_changed(self.draft_changed)
        self.update_confirmation()

    def on_unmount(self):
        self.state.off_resolved_changed(self.draft_changed)

    def draft_changed(self, paths):
        self.update_confirmation()
        if paths & self.choices.keys():
            self.run_worker(self.refresh_catalogs(self.arguments()),
                            group='command-catalogs', exclusive=True)

    async def on_button_pressed(self, event: Button.Pressed):
        event.stop()
        if event.button.id == 'command-apply':
            await self.action_submit()
        else:
            self.action_cancel()

    async def action_submit(self):
        self.form.finish()
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
        if self.is_attached and arguments == self.arguments():
            self.dismiss(arguments)

    def arguments(self):
        return {name: self.state.get_resolved_value(name) for name in self.form.values}

    async def refresh_catalogs(self, arguments):
        self.query_one('#command-apply', Button).disabled = True
        try:
            edited = self.definition.edited(arguments)
            fields = await self.app.preparation.run_thread(
                lambda: asyncio.run(edited.prepare_fields()))
        except (KeyError, ValueError, TypeError, NativePiUnavailable) as error:
            if self.is_attached and arguments == self.arguments():
                self.notify(str(error), title='Configuration choices', severity='error')
            return
        if not self.is_attached or arguments != self.arguments():
            return
        for parameter in fields:
            if parameter.name in self.choices:
                self.choices[parameter.name].parameter = parameter
                self.form.values[parameter.name].editor.paint()
        self.update_confirmation()

    def update_confirmation(self):
        confirmed = self.query_one('#command-confirmed', Checkbox)
        confirmed.value = False
        self.query_one('#command-apply', Button).disabled = True
        arguments = self.arguments()
        async def prepare():
            def read():
                for name, choices in self.choices.items():
                    if not arguments[name] or arguments[name] not in choices.choices():
                        return f'Choose {name.replace("_", " ")}', False
                try:
                    return self.definition.edited(arguments).confirmation, True
                except (KeyError, ValueError, TypeError) as error:
                    return str(error), False
            confirmation, valid = await self.app.preparation.run_thread(read)
            if not self.is_attached or arguments != self.arguments():
                return
            self.query_one('#command-confirmation', Static).update(confirmation)
            confirmed.display = valid and bool(confirmation)
            self.query_one('#command-apply', Button).disabled = not valid or any(
                arguments[name] != choices.parameter.editor_default
                for name, choices in self.choices.items())
        self.run_worker(prepare, group='command-confirmation', exclusive=True)

    def action_cancel(self):
        self.dismiss(None)
