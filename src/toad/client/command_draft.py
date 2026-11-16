"""Shared command draft: the state and algorithms of an operation form.

CommandDraft owns prepared action, fields, choice projections, generated
ObjectState, derived arguments, catalog refresh and confirmation
preparation. Native forms (Textual CommandForm, Qt command dialog)
inherit this alongside their framework's modal/form capabilities.
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import field, make_dataclass
from typing import Annotated

from agent_comms.cli_verbs.cli_command import TargetAction, TargetField
from agent_comms.transport.request import CoreAccess
from agent_comms.transport.tools.sidebar import CommsPrepareTargetActionTool
from formbridge.forms.declared_fields import DeclaredField, DeclaredMetadata, FieldLabel, Multiline
from formbridge.forms.value_editing import ControlConstruction
from objectstate import ObjectState
from python_introspect import AnnotationChoices, LabelledChoices

from formbridge.forms.field_extraction import compile_decoder


class PreparedChoices(LabelledChoices, DeclaredMetadata):
    def __init__(self, item):
        self.parameter = item

    def labelled_choices(self):
        return self.parameter.labelled_choices()

    def declares(self):
        return self.parameter.declares()


class CommandText(Multiline):
    """Multiline hint for command text fields. Native editors register for it."""


class CommandDraft:
    """The draft state/algorithm of a command operation form.

    Subclasses compose this with their native form/modal and implement
    the abstract presentation methods.
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
                                 field(default=parameter.editor_default)))
        self.state = ObjectState(make_dataclass('CommandDraft', declarations)())

    def arguments(self) -> dict[str, object]:
        return {name: self.state.get_resolved_value(name) for name in self.draft_value_names()}

    def validated_action(self, arguments) -> TargetAction:
        for name in self.choices:
            self.draft_validate_field(name, arguments[name])
        return self.definition.edited(arguments)

    async def refresh_catalogs(self, arguments, run_thread, is_alive):
        """Refresh choice projections from Core. run_thread runs a callable
        off the UI loop; is_alive returns False when the form is gone."""
        while is_alive():
            edited = self.definition.edited(arguments)
            prepared = await run_thread(
                lambda: self.core.call(CommsPrepareTargetActionTool(action=edited)))
            if not is_alive():
                return
            current = self.arguments()
            if arguments != current:
                arguments = current
                continue
            self.definition = prepared
            for parameter in prepared.fields:
                if parameter.name in self.choices:
                    self.choices[parameter.name].parameter = parameter
                    self.repaint_choice(parameter.name)
            break

    @abstractmethod
    def draft_value_names(self) -> dict[str, object]:
        """The form's value name → view mapping."""

    @abstractmethod
    def draft_validate_field(self, name: str, value: object) -> None:
        """Validate one field value."""

    @abstractmethod
    def repaint_choice(self, name: str) -> None:
        """Repaint the editor for a choice whose options changed."""
