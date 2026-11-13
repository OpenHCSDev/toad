"""The same declared form in an object's sidebar and its context editor."""
from formbridge.forms.parameter_info_types import DirectDataclassInfo, ParameterInfo
from textual import events
from textual.widgets import Static
from toad.forms.form_view import FieldView, ValueView, GroupView, FormView
from toad.object_configuration import ObjectSettingField
from toad.widgets.acting_button import ActingButton


class ObjectFieldView(FieldView):
    field_type = ObjectSettingField

    @classmethod
    def family(cls):
        return ObjectFieldView




class ResetSettingButton(ActingButton):
    """Reset uses the parameter's own signature, including lazy None defaults."""
    def __init__(self, field):
        super().__init__("Reset")
        self.field = field

    async def act(self):
        self.field.reset()
        self.query_ancestor(ObjectValueView).editor.feedback = ""


class ObjectValueView(ValueView, ObjectFieldView, shows=(ParameterInfo,)):
    def __init__(self, field):
        super().__init__(field)
        self.source = Static("", markup=False)
        self.reset = ResetSettingButton(field)
        self.listen(events.Mount, lambda event: self.mark(False))

    def compose(self):
        yield from super().compose()
        yield self.source
        yield self.reset

    def mark(self, changed):
        local = self.field.allows_override
        explicit = local and self.field.state.parameters[self.field.path.value] is not None
        super().mark(explicit)
        if self.editor.is_mounted:
            self.editor.paint_value()
        if explicit:
            self.source.update("Override for this object")
        else:
            scope, owner = self.field.state.get_provenance(self.field.path.value)
            self.source.update("Inherited from global defaults" if local else "Global setting · applies to every view")
            self.source.tooltip = f"{owner.__module__}.{owner.__qualname__} · {scope or 'global'}"


class ObjectGroupView(GroupView, ObjectFieldView, shows=(DirectDataclassInfo,)):
    field_family = ObjectFieldView


class ObjectFormView(FormView):
    field_family = ObjectFieldView
