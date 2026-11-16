"""The shared form edits one backend-declared operation and its catalogs."""
from __future__ import annotations

import asyncio
from abc import abstractmethod

from agent_comms.cli_support.cli_failures import CLI_FAILURES
from agent_comms.cli_verbs.cli_command import TargetAction
from agent_comms.cli_verbs.target_fields import TargetField
from agent_comms.config_options import ModelConfigOption
from agent_comms.execution.login import run_login
from agent_comms.transport.request import CoreAccess
from toad.client.command_draft import CommandDraft, CommandText, PreparedChoices
from toad.client.host import CommandOrigin
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.scalar import Scalar
from textual.document._editing import EditingMode
from textual.events import Mount, Unmount
from textual.screen import Screen
from textual.widgets import Button, Static

from textual.worker import Worker, WorkerFailed
from toad.forms.editors import MultilineEditor, ValueEditor
from toad.forms.form_view import InlineFormView
from toad.native_style import (
    AutoWidth,
    DockedBottom,
    EllipsisOverflow,
    FillHeight,
    SideMargin,
)
from toad.screens.modal import (
    CenteredScreen,
    DismissibleScreen,
    ModalPanel,
    ModalScreen,
    ShadedScreen,
)
from toad.widget_actions import DismissibleControl, WidgetAction
from toad.widgets.acting_button import ConfirmButton, Confirms, DismissButton
from toad.widgets.checkbox import Checkbox
from toad.widgets.model_selection import ModelSelection
from toad.worker_group import WorkerGroup




class CommandTextEditor(MultilineEditor, shows=(CommandText,)):
    height = Scalar.from_number(5)


class CatalogField(ValueEditor, Button, shows=(ModelConfigOption,)):
    """The shared model selector edits the form's canonical draft value."""

    def bind_control(self):
        self.paint()

    def paint(self):
        parameter = self.field.metadata(PreparedChoices).parameter
        current = parameter.choice_value(self.field.value)
        self.label = next((choice.name for choice in parameter.options
                           if choice.value == current), 'Choose / connect a provider…')

    @on(Button.Pressed)
    def on_button_pressed(self, event: Button.Pressed):
        event.stop()
        self.choose()

    @work(exclusive=True)
    async def choose(self):
        value = await self.app.push_screen_wait(CatalogChoiceDialog(self))
        if value is not None and self.is_attached:
            self.send(self.field.metadata(PreparedChoices).parameter.editor_value(value))


class CatalogFieldSelection(ModelSelection):
    def __init__(self, editor: CatalogField):
        self.editor = editor
        super().__init__()

    @property
    def choices(self):
        return tuple(choice for choice in self.editor.field.metadata(PreparedChoices).parameter.options
                     if choice.value is not None)

    @property
    def current(self):
        return self.editor.field.metadata(PreparedChoices).parameter.choice_value(self.editor.field.value)

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
        command = self.editor.query_ancestor(CommandForm)
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

    async def apply(self, context: CommandForm) -> None:
        await context.confirm()


class CommandBox(ModalPanel):
    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.width = 68
        self.styles.max_width = "95%"
        self.styles.height = "90%"
        self.styles.padding = (1, 2)


class CommandFormScroll(FillHeight, VerticalScroll):
    """The form scrolls within the space left above its fixed command footer."""


class CommandTitle(EllipsisOverflow, Static):
    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.max_height = 3


class CommandButtons(DockedBottom, Horizontal):
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


class CommandForm(CommandDraft, Confirms, DismissibleControl, Vertical, actions=(ApplyCommandAction,)):
    """One backend operation, embedded in a panel or presented as a dialog."""
    def __init__(self, definition: TargetAction, target: str, fields: tuple[TargetField, ...],
                 core: CoreAccess):
        super().__init__()
        self.init_draft(definition, target, fields, core)
        self.form = InlineFormView.whole(self.state)

    def compose(self) -> ComposeResult:
        yield CommandTitle(f"{self.definition.label} — {self.target}", markup=False)
        with CommandFormScroll():
            yield CommandConfirmation('', markup=False)
            yield self.form
            yield CommandConfirmed('I confirm this operation')
        with CommandButtons():
            yield ApplyCommandButton('Apply', variant='primary')
            yield CancelCommandButton('Cancel')

    @abstractmethod
    async def submit(self, arguments: dict[str, str | None]) -> None: ...

    def finish(self) -> None:
        self.form.finish()

    def dismiss_control(self) -> None:
        """An embedded form discards its draft without closing the containing view."""
        for path in self.state.parameters:
            self.state.reset_parameter(path)

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
                await self.submit(arguments)
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

    def draft_value_names(self):
        return self.form.values

    def draft_validate_field(self, name, value):
        self.form.values[name].field.validate(value)

    def repaint_choice(self, name):
        editor = self.form.values[name].editor
        editor.call_after_refresh(editor.paint_value)

    def draft_alive(self) -> bool:
        return self.is_attached

    async def draft_run_thread(self, work):
        return await self.app.preparation.run_thread(work)

    def catalogs_refreshed(self) -> None:
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


class CommandDialog(CommandForm, ShadedScreen, CenteredScreen, DismissibleScreen[dict[str, str | None]]):
    """The shared operation form in its modal presentation."""

    def compose(self) -> ComposeResult:
        with CommandBox():
            yield from super().compose()

    async def submit(self, arguments: dict[str, str | None]) -> None:
        self.dismiss(arguments)

    def dismiss_control(self) -> None:
        self.dismiss(None)


class ScreenCommandOrigin(CommandOrigin):
    """The screen a command started on; its dialog opens only while that screen still shows."""

    def __init__(self, screen: Screen) -> None:
        self.screen = screen

    def current(self) -> bool:
        return self.screen.app.screen is self.screen

    async def edit(self, definition: TargetAction, title: str, fields: tuple[TargetField, ...],
                   core: CoreAccess) -> dict[str, str | None] | None:
        return await self.screen.app.push_screen_wait(CommandDialog(definition, title, fields, core))
