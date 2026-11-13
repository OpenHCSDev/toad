"""The shared form edits one backend-declared operation and its catalogs."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, make_dataclass
from typing import Annotated, get_args, get_origin

from agent_comms.cli_support.cli_failures import CLI_FAILURES
from agent_comms.cli_verbs.cli_command import PreparedTargetAction, TargetAction
from agent_comms.cli_verbs.target_fields import ChoiceTargetField, TargetField
from agent_comms.config_options import ModelConfigOption
from agent_comms.errors import RouteChangedError
from agent_comms.execution.login import run_login
from agent_comms.execution.native_failures import NativePiUnavailable
from agent_comms.nominal.field_codec import compile_decoder
from agent_comms.transport.request import CoreAccess
from agent_comms.transport.tools.sidebar import CommsPrepareTargetActionTool
from formbridge.forms.declared_fields import DeclaredMetadata, Multiline
from objectstate import ObjectState
from python_introspect import AnnotationChoices, FieldLabel
from python_introspect.choices import LabelledChoices
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.css.scalar import Scalar
from textual.document._editing import EditingMode
from textual.events import Mount, Unmount
from textual.widgets import Button, Static

from textual.worker import Worker, WorkerFailed
from toad.forms.editors import MultilineEditor, ValueEditor
from toad.forms.form_view import InlineFormView
from toad.native_style import AutoWidth, EllipsisOverflow, SideMargin
from toad.screens.modal import (
    CenteredScreen,
    DismissibleScreen,
    ModalPanel,
    ModalScreen,
    ShadedScreen,
)
from toad.widget_actions import WidgetAction
from toad.widgets.acting_button import ConfirmButton, Confirms, DismissButton
from toad.widgets.checkbox import Checkbox
from toad.widgets.model_selection import ModelSelection
from toad.worker_group import WorkerGroup


@dataclass(eq=False)
class PreparedChoices(LabelledChoices, DeclaredMetadata):
    """The catalog last prepared for a draft, not another copy of its value."""
    parameter: ChoiceTargetField

    def labelled_choices(self):
        return self.parameter.choices

    def declares(self):
        """The prepared parameter names its own editors first; any choices editor follows."""
        yield from self.parameter.editor_declarations
        yield from super().declares()


class CommandText(Multiline):
    """A command parameter of several lines; the command form shows it five rows tall."""


class CommandTextEditor(MultilineEditor, shows=(CommandText,)):
    height = Scalar.from_number(5)


class CatalogField(ValueEditor, Button, shows=(ModelConfigOption,)):
    """The shared model selector edits the form's canonical draft value."""

    def bind_control(self):
        self.paint()

    def paint(self):
        self.label = next((choice.name for choice in self.field.metadata(PreparedChoices).parameter.options
                           if choice.value == self.field.value), 'Choose / connect a provider…')

    @on(Button.Pressed)
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

    @on(Mount)
    def on_mount(self):
        self.focus_content(False)

    def select_model(self, model_id: str):
        self.screen.dismiss(model_id)

    def dismiss_control(self) -> None:
        self.screen.dismiss(None)

    @work(exclusive=True)
    async def connect_provider(self):
        command = self.editor.query_ancestor(CommandDialog)
        with self.app.suspend():
            result = await asyncio.to_thread(run_login)
        if result == 0 and self.is_attached:
            await command.refresh_catalogs(command.arguments())
            self.configuration_changed()
        elif self.is_attached:
            self.app.notify(f'Provider login exited with status {result}',
                            title='Provider login', severity='warning', markup=False)
        if self.is_attached:
            self.search_input.focus()


class CatalogChoiceDialog(ShadedScreen, CenteredScreen, ModalScreen[str]):
    def __init__(self, editor: CatalogField):
        super().__init__()
        self.editor = editor

    def compose(self):
        yield CatalogFieldSelection(self.editor)


class ViewAction(WidgetAction, affix="Action"):
    pass


class ApplyCommandAction(ViewAction):
    title = 'Apply'
    keys = {EditingMode: ('ctrl+enter',)}
    show = True

    async def apply(self, context: CommandDialog) -> None:
        await context.confirm()


class CommandBox(ModalPanel):
    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.width = 68
        self.styles.max_width = "95%"
        self.styles.height = "90%"
        self.styles.padding = (1, 2)


class CommandTitle(EllipsisOverflow, Static):
    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.max_height = 3


class CommandButtons(Horizontal):
    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.height = 3
        self.styles.align_horizontal = "center"


class CommandButton(AutoWidth, SideMargin, Button):
    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.min_width = 12


class ApplyCommandButton(ConfirmButton, CommandButton):
    """Applies the confirmed command."""


class CancelCommandButton(DismissButton, CommandButton):
    """Closes the dialog without applying."""


class CommandConfirmation(Static):
    """What applying the command will do."""


class CommandConfirmed(Checkbox):
    """The user's confirmation of that operation."""


class CommandPreparation(WorkerGroup):
    """One preparation follows the current draft without restarting on each edit."""


class CommandDialog(Confirms, ShadedScreen, CenteredScreen, DismissibleScreen[dict[str, str | None]], actions=(ApplyCommandAction,)):
    def __init__(self, definition: TargetAction, target: str, fields: tuple[TargetField, ...],
                 core: CoreAccess):
        super().__init__()
        self.definition, self.target, self.core = definition, target, core
        self.choices = {}
        declarations = []
        for parameter in fields:
            hints = [FieldLabel(parameter.label), parameter.description]
            if get_origin(parameter.annotation) is Annotated:
                hints.extend(item for item in get_args(parameter.annotation)[1:]
                             if not isinstance(item, AnnotationChoices))
            hints.extend(parameter.editor_hints(
                lambda item: self.choices.setdefault(item.name, PreparedChoices(item))))
            if parameter.multiline:
                hints.append(CommandText())
            declarations.append((parameter.name, Annotated[compile_decoder(parameter.annotation).editor_annotation, *hints],
                                 field(default=parameter.editor_default)))
        self.state = ObjectState(make_dataclass('CommandDraft', declarations)())
        self.form = InlineFormView.whole(self.state)

    def compose(self) -> ComposeResult:
        with CommandBox():
            yield CommandTitle(f"{self.definition.label} — {self.target}", markup=False)
            with VerticalScroll():
                yield CommandConfirmation('', markup=False)
                yield self.form
            yield CommandConfirmed('I confirm this operation')
            with CommandButtons():
                yield ApplyCommandButton('Apply', variant='primary')
                yield CancelCommandButton('Cancel')

    async def confirm(self) -> None:
        button = self.query_one(ApplyCommandButton)
        if button.disabled:
            return
        self.form.finish()
        button.disabled = True
        try:
            try:
                await CommandPreparation.wait_on(self)
            except WorkerFailed:
                # Preparation reports its original error through its own handler.
                return
            if not self.is_attached or any(view.editor.feedback for view in self.form.values.values()):
                return
            arguments = self.arguments()
            confirmed = self.query_one(CommandConfirmed).value
            try:
                await self.app.preparation.run_thread(
                    lambda: self.validated_action(arguments).with_confirmation(confirmed))
            except CLI_FAILURES as error:
                self.app.show_error(error, self.definition.label)
                self.update_confirmation()
                return
            if self.is_attached and arguments == self.arguments():
                self.dismiss(arguments)
        finally:
            if self.is_attached:
                button.disabled = False

    @on(Mount)
    def on_mount(self):
        self.state.on_resolved_changed(self.draft_changed)
        self.prepare_current()
        self.update_confirmation()

    @on(Unmount)
    def on_unmount(self):
        self.state.off_resolved_changed(self.draft_changed)

    def draft_changed(self, paths):
        self.prepare_current()
        self.update_confirmation()


    def prepare_current(self) -> None:
        if not CommandPreparation.running_on(self):
            CommandPreparation.run_on(self, self.refresh_catalogs(self.arguments()), exit_on_error=False)

    @on(Worker.StateChanged)
    async def preparation_changed(self, event: Worker.StateChanged) -> None:
        if (event.worker.node is self and event.worker.group == CommandPreparation.group
                and event.worker.is_finished and self.is_attached):
            try:
                await event.worker.wait()
            except WorkerFailed as error:
                self.query_one(CommandConfirmation).update("Could not load choices")
                self.app.show_error(error.error, self.definition.label)
            else:
                self.update_confirmation()

    def validated_action(self, arguments) -> TargetAction:
        """The same declared catalog constraints guard the preview and submission."""
        for name in self.choices:
            self.form.values[name].field.validate(arguments[name])
        return self.definition.edited(arguments)

    def arguments(self):
        return {name: self.state.get_resolved_value(name) for name in self.form.values}

    async def refresh_catalogs(self, arguments):
        while self.is_attached:
            edited = self.definition.edited(arguments)
            prepared = await self.app.preparation.run_thread(
                lambda: self.core.call(CommsPrepareTargetActionTool(action=edited)))
            if not self.is_attached:
                return
            current = self.arguments()
            if arguments != current:
                arguments = current
                continue
            self.definition = prepared
            for parameter in prepared.fields:
                if parameter.name in self.choices:
                    self.choices[parameter.name].parameter = parameter
                    self.form.values[parameter.name].editor.paint()
            break
        if self.is_attached:
            self.update_confirmation()

    def update_confirmation(self):
        confirmed = self.query_one(CommandConfirmed)
        confirmed.value = False
        arguments = self.arguments()
        if CommandPreparation.running_on(self):
            self.query_one(CommandConfirmation).update("Loading choices…")
            confirmed.display = False
            return
        async def prepare():
            def read():
                try:
                    return self.validated_action(arguments).confirmation, True
                except (TypeError, ValueError) as error:
                    return str(error), False
            confirmation, valid = await self.app.preparation.run_thread(read)
            if not self.is_attached or arguments != self.arguments() or CommandPreparation.running_on(self):
                return
            self.query_one(CommandConfirmation).update(confirmation)
            confirmed.display = valid and bool(confirmation)
        self.run_worker(prepare, group='command-confirmation', exclusive=True)
