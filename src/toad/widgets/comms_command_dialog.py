"""The shared form edits one backend-declared operation and its catalogs."""
from __future__ import annotations

import asyncio
from abc import abstractmethod

from agent_comms.cli_verbs.cli_command import TargetAction
from agent_comms.cli_verbs.target_fields import TargetField
from agent_comms.config_options import ModelConfigOption
from agent_comms.execution.login import run_login
from agent_comms.transport.request import CoreAccess
from formbridge.key_declarations import TextEntryMode
from toad.client.command_draft import CommandFormCore, CommandText, PreparedChoices
from toad.client.host import CommandOrigin
from toad.client.model_selection import CatalogChoiceSelection, CatalogModelField
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.scalar import Scalar

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


class CatalogField(CatalogModelField, ValueEditor, Button, shows=(ModelConfigOption,)):
    """The shared model selector edits the form's canonical draft value."""

    def bind_control(self):
        self.paint()

    def paint(self):
        self.label = self.catalog_label()

    @on(Button.Pressed)
    def on_button_pressed(self, event: Button.Pressed):
        event.stop()
        self.choose()

    @work(exclusive=True)
    async def choose(self):
        value = await self.app.push_screen_wait(CatalogChoiceDialog(self))
        if value is not None and self.is_attached:
            self.apply_catalog_choice(value)


class CatalogFieldSelection(CatalogChoiceSelection, ModelSelection):
    def __init__(self, editor: CatalogField):
        self.editor = editor
        super().__init__()

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
    keys = {TextEntryMode: ('ctrl+enter',)}
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


class CommandForm(CommandFormCore, Confirms, DismissibleControl, Vertical, actions=(ApplyCommandAction,)):
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
    async def handle_submission(self, arguments: dict[str, str | None]) -> None: ...

    def dismiss_control(self) -> None:
        """An embedded form discards its draft without closing the containing view."""
        for path in self.state.parameters:
            self.state.reset_parameter(path)

    def apply_enabled(self) -> bool:
        return not self.query_one(ApplyCommandButton).disabled

    def set_apply_enabled(self, enabled: bool) -> None:
        self.query_one(ApplyCommandButton).disabled = not enabled

    @on(Mount)
    def on_mount(self):
        self.open_draft()

    @on(Unmount)
    def on_unmount(self):
        self.close_draft()

    @on(Worker.StateChanged)
    async def preparation_changed(self, event: Worker.StateChanged) -> None:
        if (event.worker.node is self and event.worker.group == CommandPreparation.group
                and event.worker.is_finished and self.is_attached):
            try:
                await event.worker.wait()
            except WorkerFailed as error:
                self.preparation_failed(error.error)
            else:
                self.update_confirmation()

    def repaint_choice(self, name):
        editor = self.form.values[name].editor
        editor.call_after_refresh(editor.paint_value)

    def draft_alive(self) -> bool:
        return self.is_attached

    async def draft_run_thread(self, work):
        return await self.app.preparation.run_thread(work)

    def preparing(self) -> bool:
        return CommandPreparation.running_on(self)

    def start_preparation(self, preparation) -> None:
        CommandPreparation.run_on(self, preparation, exit_on_error=False)

    async def preparation_settled(self) -> bool:
        try:
            await CommandPreparation.wait_on(self)
        except WorkerFailed:
            # Preparation reports its original error through its own handler.
            return False
        return True

    def start_confirmation(self, reading) -> None:
        self.run_worker(reading, group='command-confirmation', exclusive=True)

    def reset_confirmed(self) -> None:
        self.query_one(CommandConfirmed).value = False

    def show_confirmation(self, text: str, confirmable: bool) -> None:
        self.query_one(CommandConfirmation).update(text)
        self.query_one(CommandConfirmed).display = confirmable

    def is_confirmed(self) -> bool:
        return self.query_one(CommandConfirmed).value

    def draft_refused(self) -> bool:
        return any(view.editor.feedback for view in self.form.values.values())

    def draft_failed(self, error: BaseException) -> None:
        self.app.show_error(error, self.definition.label)


class CommandDialog(CommandForm, ShadedScreen, CenteredScreen, DismissibleScreen[dict[str, str | None]]):
    """The shared operation form in its modal presentation."""

    def compose(self) -> ComposeResult:
        with CommandBox():
            yield from super().compose()

    async def handle_submission(self, arguments: dict[str, str | None]) -> None:
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
