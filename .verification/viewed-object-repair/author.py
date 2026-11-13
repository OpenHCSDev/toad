import json
from pathlib import Path
root=Path.cwd(); ops=[]
def patch(f,t,o,n): ops.append(dict(operation='patch_target',file_path=str(root/f),target_qualname=t,replacements=[dict(old_source=o,new_source=n)]))
def insert(f,t,s): ops.append(dict(operation='insert_before_target',file_path=str(root/f),target_qualname=t,source=s))
def imp(f,s): ops.append(dict(operation='ensure_import',file_path=str(root/f),import_source=s))
f='src/toad/forms/editors.py'
imp(f,'from ui_theme.scheme import MutedColour')
insert(f,'ValueEditor.control_mounted','''    @property
    def previewing(self) -> bool:
        """The raw field inherits; its resolved value is only a preview."""
        return self.field.state.parameters[self.field.path.value] is None and self.field.value is not None

    def paint_value(self) -> None:
        self.paint()
        self.styles.color = self.app.colours.colour(MutedColour) if self.previewing else None
        self.styles.text_style = "dim" if self.previewing else ""

''')
patch(f,'ValueEditor.control_mounted','self.call_after_refresh(self.paint)','self.call_after_refresh(self.paint_value)')
insert(f,'LineEditor.control_arguments','''    def current_text(self) -> str:
        return "" if self.previewing else self.value_text(self.field.value)

''')
patch(f,'LineEditor.control_arguments','''            "value": self.value_text(self.field.value),''','''            "value": self.current_text(),
            "placeholder": self.value_text(self.field.value) if self.previewing else self.field.placeholder,''')
patch(f,'LineEditor.finish','self.value == self.value_text(self.field.value)','self.value == self.current_text()')
patch(f,'LineEditor.paint','''        self.value = self.value_text(self.field.value)''','''        self.placeholder = self.value_text(self.field.value) if self.previewing else self.field.placeholder
        self.value = self.current_text()''')
patch(f,'SelectEditor.control_arguments','''        listed = any(value == choice for _, choice in options)''','''        listed = not self.previewing and any(value == choice for _, choice in options)''')
patch(f,'SelectEditor.control_arguments','''            "prompt": self.field.placeholder if value is None else str(value),''','''            "prompt": next((label for label, choice in options if choice == value),
                           self.field.placeholder if value is None else str(value)),''')
patch(f,'SelectEditor.paint','''            self.value = value if self.lists(value) else Select.NULL''','''            self.value = value if not self.previewing and self.lists(value) else Select.NULL''')
f='src/toad/forms/form_view.py'
patch(f,'FormView.values_changed','editor.paint()','editor.paint_value()')
f='src/toad/object_configuration.py'
insert(f,'ObjectSettingField.edit','''    def reset(self) -> None:
        """The writer resets its actual parameter to that parameter's signature default."""
        state = self.state if self.allows_override else self.state.defaults
        state.reset_parameter(self.path.value)
        if state is self.state.defaults:
            self.state.global_settings.save_sync()

''')
f='src/toad/forms/object_configuration.py'
patch(f,'InheritSettingButton', '''class InheritSettingButton(ActingButton):
    def __init__(self, field):
        super().__init__("Override here")
        self.field = field

    async def act(self):
        if self.field.state.parameters[self.field.path.value] is None:
            self.field.edit(self.field.value)
        else:
            self.field.state.reset_parameter(self.field.path.value)''','''class ResetSettingButton(ActingButton):
    """Reset uses the parameter's own signature, including lazy None defaults."""
    def __init__(self, field):
        super().__init__("Reset")
        self.field = field

    async def act(self):
        self.field.reset()''')
patch(f,'ObjectValueView.__init__','self.inherit = InheritSettingButton(field)','self.reset = ResetSettingButton(field)')
patch(f,'ObjectValueView.compose','yield self.inherit','yield self.reset')
patch(f,'ObjectValueView.mark', '''        self.inherit.display = local
        self.inherit.label = "Use global default" if explicit else "Override here"''','''        if self.editor.is_mounted:
            self.editor.paint_value()''')
Path('.verification/viewed-object-repair/preview.plan.json').write_text(json.dumps({'recipes':[{'recipe_id':'paint-inherited-previews-and-reset-the-original-parameter','operations':ops}]},indent=2))
