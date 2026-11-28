"""The same declared form in an object's sidebar and its context editor."""
from formbridge.forms.parameter_info_types import DirectDataclassInfo, ParameterInfo
from textual import events
from textual.widgets import Static
from toad.form_family import ObjectFieldViews, ObjectValueFields
from toad.forms.form_view import FieldView, ValueView, GroupView, FormView
from toad.widgets.acting_button import ActingButton


class ObjectFieldView(ObjectFieldViews, FieldView):
    @classmethod
    def family(cls):
        return ObjectFieldView


class ResetSettingButton(ActingButton):
    """Reset uses the parameter's own signature, including lazy None defaults."""
    def __init__(self):
        super().__init__(ObjectValueFields.reset_label)

    async def act(self):
        self.query_ancestor(ObjectValueView).reset_field()


class ObjectValueView(ObjectValueFields, ValueView, ObjectFieldView, shows=(ParameterInfo,)):
    def __init__(self, field):
        super().__init__(field)
        self.source = Static("", markup=False)
        self.reset = ResetSettingButton()
        self.listen(events.Mount, lambda event: self.mark(False))

    def compose(self):
        yield from super().compose()
        yield self.source
        yield self.reset

    def mark(self, changed):
        overridden = self.overridden()
        super().mark(overridden)
        if self.editor.is_mounted:
            self.editor.paint_value()
        self.source.update(self.source_text())
        if not overridden:
            self.source.tooltip = self.source_detail()


class ObjectGroupView(GroupView, ObjectFieldView, shows=(DirectDataclassInfo,)):
    field_family = ObjectFieldView


class ObjectFormView(FormView):
    field_family = ObjectFieldView
