"""The same declared form in an object's sidebar and its context editor."""
from formbridge.forms.parameter_info_types import DirectDataclassInfo, ParameterInfo
from textual import events
from textual.widgets import Button, Static
from toad.forms.form_view import FieldView, ValueView, GroupView, FormView
from toad.object_configuration import ObjectSettingField
from toad.widgets.acting_button import ActingButton


class ObjectFieldView(FieldView):
    field_type = ObjectSettingField

    @classmethod
    def admits(cls, field):
        return field.state.shows(field.path.value)


class InheritSettingButton(ActingButton):
    def __init__(self, field):
        super().__init__("Use global default")
        self.field = field

    async def act(self):
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
        explicit = self.field.state.parameters[self.field.path.value] is not None
        super().mark(explicit)
        self.inherit.disabled = not explicit
        scope, owner = self.field.state.get_provenance(self.field.path.value)
        self.source.update("Override for this object" if explicit else
                           f"Inherited from global defaults · {owner.__name__}")


class ObjectGroupView(GroupView, ObjectFieldView, shows=(DirectDataclassInfo,)):
    field_family = ObjectFieldView


class ObjectFormView(FormView):
    field_family = ObjectFieldView
