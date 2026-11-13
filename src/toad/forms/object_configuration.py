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




class InheritSettingButton(ActingButton):
    def __init__(self, field):
        super().__init__("Override here")
        self.field = field

    async def act(self):
        if self.field.state.parameters[self.field.path.value] is None:
            self.field.edit(self.field.value)
        else:
            self.field.state.reset_parameter(self.field.path.value)


class ObjectValueView(ValueView, ObjectFieldView, shows=(ParameterInfo,)):
    def __init__(self, field):
        super().__init__(field)
        self.source = Static("", markup=False)
        self.inherit = InheritSettingButton(field)
        self.listen(events.Mount, lambda event: self.mark(False))

    def compose(self):
        yield from super().compose()
        yield self.source
        yield self.inherit

    def mark(self, changed):
        local = self.field.allows_override
        explicit = local and self.field.state.parameters[self.field.path.value] is not None
        super().mark(explicit)
        self.inherit.display = local
        self.inherit.label = "Use global default" if explicit else "Override here"
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
