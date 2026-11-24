"""Textual's unified interactive dialog panel: renders `DialogSpec` inline in `Prompt`.

Sibling of `QtInteractiveDialog` over the same `InteractiveDialogOwner` state machine
(`toad.client.interactive_dialog`): single-choice questions, multi-select checklists,
confirmations, text/number inputs, and ACP `elicitation/create` forms render here.
"""

from __future__ import annotations

from metaclass_registry.mro_dispatch import MroDispatch, handles
from textual import containers, on, widgets
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widget import Widget
from textual.widgets.option_list import Option
from textual.widgets.selection_list import Selection

from toad.client.interactive_dialog import (
    ConfirmDialogField,
    DialogField,
    DialogSpec,
    InteractiveDialogOwner,
    MultiSelectDialogField,
    NumberDialogField,
    SingleSelectDialogField,
    TextDialogField,
)
from toad.native_style import (
    FillWidth,
    MutedText,
    PrimaryText,
    ScrollsVertically,
    SidePadding,
    SpacedBelow,
    StartsHidden,
)


class DialogTitle(PrimaryText, SpacedBelow, widgets.Label):
    """Its look is its bases."""


class DialogDescription(MutedText, SpacedBelow, widgets.Label):
    """Its look is its bases."""


class DialogErrorLabel(FillWidth, widgets.Label):
    """Per-field validation error text."""


class DialogFieldsContainer(ScrollsVertically, containers.VerticalGroup):
    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.max_height = "45vh"


class DialogActionsRow(containers.HorizontalGroup):
    """Submit / Decline / Cancel controls."""


class DialogActionButton(widgets.Button):
    """One dialog action button; each subclass owns the dialog method it invokes."""

    def invoke(self, dialog: PromptDialog) -> None:
        raise NotImplementedError


class SubmitDialogButton(DialogActionButton):
    def __init__(self, label: str) -> None:
        super().__init__(label, id="dialog-submit", variant="primary")

    def invoke(self, dialog: PromptDialog) -> None:
        dialog.commit_dialog()


class DeclineDialogButton(DialogActionButton):
    def __init__(self, label: str) -> None:
        super().__init__(label, id="dialog-decline")

    def invoke(self, dialog: PromptDialog) -> None:
        dialog.decline_dialog()


class CancelDialogButton(DialogActionButton):
    def __init__(self, label: str) -> None:
        super().__init__(label, id="dialog-cancel")

    def invoke(self, dialog: PromptDialog) -> None:
        dialog.cancel_dialog()


class PromptDialog(
    InteractiveDialogOwner,
    MroDispatch,
    SidePadding,
    StartsHidden,
    containers.VerticalGroup,
):
    """Inline interactive dialog rendered in place of the prompt editor."""

    BINDINGS = [
        Binding("escape", "cancel_dialog", "Cancel", show=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.init_dialog_owner()
        self._error_widgets: dict[str, DialogErrorLabel] = {}
        self._other_multi_previous: dict[str, str] = {}

    def action_cancel_dialog(self) -> None:
        self.cancel_dialog()

    def present_dialog(self, spec: DialogSpec) -> None:
        self._error_widgets.clear()
        self._other_multi_previous.clear()
        self.display = True
        self.refresh(recompose=True, layout=True)

    def clear_dialog(self) -> None:
        self._error_widgets.clear()
        self._other_multi_previous.clear()
        self.display = False
        self.refresh(recompose=True, layout=True)

    def show_dialog_errors(self, errors: dict[str, str]) -> None:
        for name, label in self._error_widgets.items():
            text = errors.get(name, "")
            label.update(text)
            label.display = bool(text)

    def compose(self) -> ComposeResult:
        spec = self.dialog_spec
        if spec is None:
            return
        if spec.title:
            yield DialogTitle(spec.title, markup=False)
        if spec.message:
            yield DialogDescription(spec.message, markup=False)
        quick = spec.is_quick_choice
        with DialogFieldsContainer():
            for field in spec.fields:
                if not quick:
                    yield DialogTitle(field.title, markup=False)
                if field.description:
                    yield DialogDescription(field.description, markup=False)
                yield from next(self.handlers_for(field))(field, quick)
                error_label = DialogErrorLabel("", markup=False)
                error_label.display = False
                self._error_widgets[field.name] = error_label
                yield error_label
        with DialogActionsRow():
            if not quick:
                yield SubmitDialogButton(spec.submit_label)
                yield DeclineDialogButton(spec.decline_label)
            yield CancelDialogButton(spec.cancel_label)

    @handles(SingleSelectDialogField)
    def compose_single_select(
        self, field: SingleSelectDialogField, quick: bool,
    ) -> tuple[Widget, ...]:
        if quick:
            options = [
                Option(
                    f"{option.label} — {option.description}" if option.description else option.label,
                    id=option.value,
                )
                for option in field.options
            ]
            option_list = widgets.OptionList(*options, name=field.name, classes="dialog-quick-select")
            return (option_list,)
        initial = self.dialog_values.get(field.name)
        buttons: list[widgets.RadioButton] = []
        for option in field.options:
            label = f"{option.label} — {option.description}" if option.description else option.label
            radio = widgets.RadioButton(label, value=(initial == option.value), name=option.value)
            buttons.append(radio)
        radio_set = widgets.RadioSet(*buttons, name=field.name)
        controls: list[Widget] = [radio_set]
        if field.allow_other:
            controls.append(widgets.Input(
                placeholder="Other (optional)...",
                name=field.name,
                classes="dialog-other-single",
            ))
        return tuple(controls)

    @handles(MultiSelectDialogField)
    def compose_multi_select(
        self, field: MultiSelectDialogField, quick: bool,
    ) -> tuple[Widget, ...]:
        selected = set(field.coerce(self.dialog_values.get(field.name)))
        selections = [
            Selection(
                f"{option.label} — {option.description}" if option.description else option.label,
                option.value,
                option.value in selected,
            )
            for option in field.options
        ]
        controls: list[Widget] = [widgets.SelectionList(*selections, name=field.name)]
        if field.allow_other:
            controls.append(widgets.Input(
                placeholder="Other (optional)...",
                name=field.name,
                classes="dialog-other-multi",
            ))
        return tuple(controls)

    @handles(ConfirmDialogField)
    def compose_confirm(self, field: ConfirmDialogField, quick: bool) -> tuple[Widget, ...]:
        return (widgets.Checkbox(field.title, value=bool(self.dialog_values.get(field.name)), name=field.name),)

    @handles(TextDialogField)
    def compose_text(self, field: TextDialogField, quick: bool) -> tuple[Widget, ...]:
        initial = str(self.dialog_values.get(field.name) or "")
        if field.multiline:
            return (widgets.TextArea(initial, name=field.name),)
        return (widgets.Input(value=initial, placeholder=field.placeholder, name=field.name),)

    @handles(NumberDialogField)
    def compose_number(self, field: NumberDialogField, quick: bool) -> tuple[Widget, ...]:
        initial = str(self.dialog_values.get(field.name) or "")
        placeholder = "Whole number" if field.integer else "Number"
        return (widgets.Input(value=initial, placeholder=placeholder, name=field.name),)

    @on(widgets.OptionList.OptionSelected, ".dialog-quick-select")
    def on_quick_selected(self, event: widgets.OptionList.OptionSelected) -> None:
        event.stop()
        if event.option_list.name and event.option_id is not None:
            self.pick_quick_option(event.option_list.name, event.option_id)

    @on(widgets.RadioSet.Changed)
    def on_radio_changed(self, event: widgets.RadioSet.Changed) -> None:
        event.stop()
        if event.radio_set.name and event.pressed.name is not None:
            self.set_dialog_value(event.radio_set.name, event.pressed.name)

    @on(widgets.SelectionList.SelectedChanged)
    def on_selection_changed(self, event: widgets.SelectionList.SelectedChanged) -> None:
        event.stop()
        if event.selection_list.name:
            chosen = list(event.selection_list.selected)
            other = self._other_multi_previous.get(event.selection_list.name)
            if other and other not in chosen:
                chosen.append(other)
            self.set_dialog_value(event.selection_list.name, chosen)

    @on(widgets.Checkbox.Changed)
    def on_checkbox_changed(self, event: widgets.Checkbox.Changed) -> None:
        event.stop()
        if event.checkbox.name:
            self.set_dialog_value(event.checkbox.name, event.value)

    @on(widgets.Input.Changed)
    def on_input_changed(self, event: widgets.Input.Changed) -> None:
        event.stop()
        name = event.input.name
        if not name:
            return
        if event.input.has_class("dialog-other-multi"):
            previous = self._other_multi_previous.get(name, "")
            if previous:
                self.toggle_dialog_option(name, previous, False)
            cleaned = event.value.strip()
            self._other_multi_previous[name] = cleaned
            if cleaned:
                self.toggle_dialog_option(name, cleaned, True)
            return
        if event.input.has_class("dialog-other-single"):
            if event.value.strip():
                self.set_dialog_value(name, event.value.strip())
            return
        self.set_dialog_value(name, event.value)

    @on(widgets.Input.Submitted)
    def on_input_submitted(self, event: widgets.Input.Submitted) -> None:
        event.stop()
        self.commit_dialog()

    @on(widgets.TextArea.Changed)
    def on_textarea_changed(self, event: widgets.TextArea.Changed) -> None:
        event.stop()
        if event.text_area.name:
            self.set_dialog_value(event.text_area.name, event.text_area.text)

    @on(widgets.Button.Pressed)
    def on_button_pressed(self, event: widgets.Button.Pressed) -> None:
        event.stop()
        event.button.invoke(self)
