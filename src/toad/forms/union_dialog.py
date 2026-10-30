"""A pending native member form; Apply alone edits its containing field."""

from __future__ import annotations

from formbridge.forms.declared_fields import DeclaredField
from textual import containers, on
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Button, Select, Static
from textual.widgets.select import NoSelection

from toad.forms.form_view import InlineFormView
from toad.forms.member_editing import UnionMembers


class UnionMemberDialog[Selection = object](ModalScreen[None]):
    """One pending member transaction, separate from the committed parent."""

    DEFAULT_CSS = '''
    UnionMemberDialog { align: center middle; background: $background 40%; }
    UnionMemberDialog #union-box { width: 68; max-width: 95%; height: 90%;
        background: $surface; border: solid $primary; padding: 1 2; }
    UnionMemberDialog #union-body { height: 1fr; }
    UnionMemberDialog #union-buttons { height: 3; }
    '''

    def __init__(self, field: DeclaredField, members: UnionMembers[Selection]) -> None:
        super().__init__()
        self.field, self.members = field, members
        choice = members.selected(field.value)
        self.selector: Select[Selection] = Select(
            [(members.label(member), member) for member in members.choices()],
            value=choice, allow_blank=False, id='union-member',
        )
        self.draft = members.draft(choice, field.value)
        self.form = InlineFormView.whole(self.draft.state)
        self.body = containers.VerticalScroll(self.form, id='union-body')
        self.feedback = Static('', markup=False)
        self.apply_button = Button('Apply', id='union-apply', variant='primary', disabled=True)

    def compose(self) -> ComposeResult:
        with containers.Vertical(id='union-box'):
            yield Static(self.field.label, markup=False)
            yield self.selector
            yield self.body
            yield self.feedback
            with containers.Horizontal(id='union-buttons'):
                yield self.apply_button
                yield Button('Cancel', id='union-cancel')

    def on_mount(self) -> None:
        self.draft.state.on_resolved_changed(self.changed)
        self.validate_draft()

    def on_unmount(self) -> None:
        self.draft.state.off_resolved_changed(self.changed)

    def changed(self, paths: set[str]) -> None:
        self.validate_draft()

    def validate_draft(self) -> None:
        try:
            self.draft.complete()
        except self.draft.refusal as error:
            self.feedback.update(str(error))
            self.apply_button.disabled = True
        else:
            self.feedback.update('')
            self.apply_button.disabled = False

    @on(Select.Changed, '#union-member')
    async def select_member(self, event: Select.Changed) -> None:
        event.stop()
        choice = self.selector.value
        if isinstance(choice, NoSelection):
            raise ValueError('A union selector requires a declared selection')
        if choice == self.draft.selection:
            return
        self.apply_button.disabled = True
        self.draft.state.off_resolved_changed(self.changed)
        await self.form.remove()
        if not self.is_attached:
            return
        self.draft = self.members.draft(choice, self.field.value)
        self.form = InlineFormView.whole(self.draft.state)
        await self.body.mount(self.form)
        self.draft.state.on_resolved_changed(self.changed)
        self.validate_draft()

    @on(Button.Pressed, '#union-apply')
    def apply_member(self, event: Button.Pressed) -> None:
        event.stop()
        self.form.finish()
        try:
            value = self.draft.complete()
        except self.draft.refusal as error:
            self.feedback.update(str(error))
            self.apply_button.disabled = True
            return
        self.field.edit(value)
        self.dismiss()

    @on(Button.Pressed, '#union-cancel')
    def cancel_member(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss()
