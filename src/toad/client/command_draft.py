"""Shared command draft: the state and algorithms of an operation form.

CommandDraft owns the prepared action, its fields, choice projections, the generated
ObjectState, the arguments read from it, catalog refresh, the confirmation text and
what Apply submits. Native forms (Textual's CommandForm, Qt's) inherit it beside their
framework's form or modal and supply the native hooks.
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Coroutine
from dataclasses import dataclass, field as dc_field, fields as draft_fields, make_dataclass
from typing import Annotated

from agent_comms.cli_support.cli_failures import CLI_FAILURES
from agent_comms.cli_verbs.cli_command import TargetAction, TargetField
from agent_comms.cli_verbs.target_fields import ChoiceTargetField
from agent_comms.nominal.field_codec import compile_decoder
from agent_comms.transport.request import CoreAccess
from agent_comms.transport.tools.sidebar import CommsPrepareTargetActionTool
from formbridge.forms.declared_fields import DeclaredField, DeclaredMetadata, Multiline
from objectstate import DottedFieldPath, ObjectState
from python_introspect import FieldLabel
from python_introspect.choices import LabelledChoices


@dataclass(eq=False)
class PreparedChoices(LabelledChoices, DeclaredMetadata):
    """The catalog last prepared for a draft, not another copy of its value."""
    parameter: ChoiceTargetField

    def labelled_choices(self):
        return self.parameter.choices

    def declares(self):
        yield from self.parameter.editor_declarations
        yield from super().declares()


class CommandText(Multiline):
    """Multiline hint for command text fields. Native editors register for it."""


class CommandDraft:
    """The draft state and algorithms of a command operation form.

    A native form composes this with its widgets, calls ``open_draft`` when it is
    shown and ``close_draft`` before it goes, ``confirm_arguments`` on Apply and
    ``preparation_failed`` when a catalog refresh fails, and supplies the hooks below.
    """

    definition: TargetAction
    core: CoreAccess
    choices: dict[str, PreparedChoices]
    state: ObjectState
    target: str

    def init_draft(self, definition: TargetAction, target: str,
                   fields: tuple[TargetField, ...], core: CoreAccess) -> None:
        self.definition, self.target, self.core = definition, target, core
        self.choices = {}
        declarations = []
        for parameter in fields:
            hints = [FieldLabel(parameter.label), parameter.description]
            hints.extend(parameter.editor_hints(
                lambda item: self.choices.setdefault(item.name, PreparedChoices(item))))
            if parameter.multiline:
                hints.append(CommandText())
            declarations.append((parameter.name, Annotated[compile_decoder(parameter.annotation).editor_annotation, *hints],
                                 dc_field(default=parameter.editor_default)))
        self.state = ObjectState(make_dataclass('CommandDraft', declarations)())

    def open_draft(self) -> None:
        """The form is shown: follow its edits and prepare its choices."""
        self.state.on_resolved_changed(self.draft_changed)
        self.prepare_current()
        self.update_confirmation()

    def close_draft(self) -> None:
        self.state.off_resolved_changed(self.draft_changed)

    def arguments(self) -> dict[str, object]:
        return {declared.name: self.state.get_resolved_value(declared.name)
                for declared in draft_fields(self.state.object_instance)}

    def validated_action(self, arguments) -> TargetAction:
        for name in self.choices:
            DeclaredField(self.state, DottedFieldPath(name)).validate(arguments[name])
        return self.definition.edited(arguments)

    def draft_changed(self, paths) -> None:
        self.prepare_current()
        self.update_confirmation()

    def prepare_current(self) -> None:
        """One preparation follows the current draft; an edit made during it is read when
        it compares its arguments again."""
        if not self.preparing():
            self.start_preparation(self.refresh_catalogs(self.arguments()))

    async def refresh_catalogs(self, arguments) -> None:
        """Refresh choice projections from Core until the arguments they were asked for
        are still the form's arguments. Core's answer only updates the choices: the action
        sent next is edited from the declared one again, never from the prepared answer,
        whose offered choices are not part of a request."""
        while self.draft_alive():
            edited = self.definition.edited(arguments)
            prepared = await self.draft_run_thread(
                lambda: self.core.call(CommsPrepareTargetActionTool(action=edited)))
            if not self.draft_alive():
                return
            current = self.arguments()
            if arguments != current:
                arguments = current
                continue
            for parameter in prepared.fields:
                if parameter.name in self.choices:
                    self.choices[parameter.name].parameter = parameter
                    self.repaint_choice(parameter.name)
            break
        if self.draft_alive():
            self.update_confirmation()

    def preparation_failed(self, error: BaseException) -> None:
        """A catalog refresh failed; its original error is shown, the choices stay as they were."""
        self.show_confirmation("Could not load choices", False)
        self.draft_failed(error)

    def update_confirmation(self) -> None:
        self.reset_confirmed()
        if self.preparing():
            self.show_confirmation("Loading choices…", False)
            return
        self.start_confirmation(self.read_confirmation(self.arguments()))

    async def read_confirmation(self, arguments) -> None:
        def read():
            try:
                return self.validated_action(arguments).confirmation, True
            except (TypeError, ValueError) as error:
                return str(error), False
        confirmation, valid = await self.draft_run_thread(read)
        if not self.draft_alive() or arguments != self.arguments() or self.preparing():
            return
        self.show_confirmation(confirmation, valid and bool(confirmation))

    async def confirm_arguments(self) -> dict[str, object] | None:
        """What Apply submits, after the current preparation; None when choices failed to
        load, an editor holds a refusal, Core refuses the action, or the draft moved on."""
        if not await self.preparation_settled():
            return None
        if not self.draft_alive() or self.draft_refused():
            return None
        arguments = self.arguments()
        confirmed = self.is_confirmed()
        try:
            await self.draft_run_thread(
                lambda: self.validated_action(arguments).with_confirmation(confirmed))
        except CLI_FAILURES as error:
            self.draft_failed(error)
            self.update_confirmation()
            return None
        return arguments if self.draft_alive() and arguments == self.arguments() else None

    @abstractmethod
    def draft_alive(self) -> bool:
        """Whether the native form is still shown."""

    @abstractmethod
    async def draft_run_thread(self, work):
        """Run Core work off the native UI loop."""

    @abstractmethod
    def preparing(self) -> bool:
        """Whether a catalog refresh is running."""

    @abstractmethod
    def start_preparation(self, preparation: Coroutine) -> None:
        """Run a catalog refresh: a failure reaches ``preparation_failed``; when it ends
        the native form calls ``update_confirmation``."""

    @abstractmethod
    async def preparation_settled(self) -> bool:
        """Wait for the running refresh; False when it failed."""

    @abstractmethod
    def start_confirmation(self, reading: Coroutine) -> None:
        """Run a confirmation read, replacing one still running."""

    @abstractmethod
    def reset_confirmed(self) -> None:
        """Clear the user's confirmation; the action it confirmed may have changed."""

    @abstractmethod
    def show_confirmation(self, text: str, confirmable: bool) -> None:
        """Show the confirmation text, and the confirm control only when confirmable."""

    @abstractmethod
    def is_confirmed(self) -> bool:
        """Whether the user confirmed the operation."""

    @abstractmethod
    def draft_refused(self) -> bool:
        """Whether an editor is holding a refusal of what was typed."""

    @abstractmethod
    def draft_failed(self, error: BaseException) -> None:
        """Show an original failure through the native error owner."""

    @abstractmethod
    def repaint_choice(self, name: str) -> None:
        """Repaint the editor for a choice whose options changed."""


class CommandFormCore(CommandDraft):
    """Shared Apply state machine for native command forms.

    Textual's ``CommandForm`` and Qt's ``QtCommandForm`` inherit this: they supply the
    three native hooks (``apply_enabled``, ``set_apply_enabled``, ``handle_submission``)
    plus the hooks ``CommandDraft`` already declares; the Apply flow itself lives here
    once. Previously both frontends restated the state machine with minor variations,
    letting the two drift.
    """

    def finish(self) -> None:
        """Commit whatever is being edited into the form state. Called before Apply reads it."""
        self.form.finish()

    async def confirm(self) -> None:
        """Apply the form: finish editing, disable Apply, read arguments, submit. The button
        is re-enabled only while the form is still alive."""
        if not self.apply_enabled():
            return
        self.finish()
        self.set_apply_enabled(False)
        try:
            arguments = await self.confirm_arguments()
            if arguments is not None:
                await self.handle_submission(arguments)
        finally:
            if self.draft_alive():
                self.set_apply_enabled(True)

    @abstractmethod
    def apply_enabled(self) -> bool:
        """Whether Apply will act on a press right now. Used to short-circuit a second press
        while a confirm is already running."""

    @abstractmethod
    def set_apply_enabled(self, enabled: bool) -> None:
        """Enable or disable Apply. Called at the top and bottom of ``confirm``."""

    @abstractmethod
    async def handle_submission(self, arguments: dict[str, object]) -> None:
        """The arguments ``confirm_arguments`` cleared: forward them to the native sink —
        dismiss a modal with them on Textual, set the Qt future and accept on Qt."""
