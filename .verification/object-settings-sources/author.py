import json
from pathlib import Path

root = Path.cwd()
ops = []
def patch(file, target, old, new):
    ops.append(dict(operation='patch_target', file_path=str(root / file), target_qualname=target,
                    replacements=[dict(old_source=old, new_source=new)]))

patch('src/toad/configured_view.py', 'ConfiguredView.configuration_panels', '''        for path in state.direct_parameter_paths():
            if state.shows(path.value):
                field = state.field(path.value)
                yield SideBar.Panel(field.label, ObjectProperties(field),
                                    id=f"settings-{path.value}", flex=True)''', '''        for path, parameter in ParameterFormService().parameters_for_state(state):
            field = state.field(path.value)
            yield SideBar.Panel(field.label, ObjectProperties(field),
                                id=f"settings-{path.value}", flex=True)''')
ops.append(dict(operation='ensure_import', file_path=str(root/'src/toad/configured_view.py'),
                import_source='from formbridge.forms.parameter_form_service import ParameterFormService'))
patch('src/toad/object_configuration.py', 'ObjectSettingField', '''    @property
    def owner_type(self):
        return DeclaredField(self.state.defaults, self.path).owner_type''', '''    @property
    def owner_type(self):
        return DeclaredField(self.state.defaults, self.path).owner_type

    @property
    def allows_override(self) -> bool:
        return self.state.admits(self.path.value)

    def edit(self, value):
        if self.allows_override:
            return super().edit(value)
        return DeclaredField(self.state.defaults, self.path).edit(value)''')
patch('src/toad/forms/object_configuration.py', 'ObjectFieldView.admits', '''        return field.state.shows(field.path.value)''', '''        return True''')
patch('src/toad/forms/object_configuration.py', 'ObjectValueView.mark', '''        explicit = self.field.state.parameters[self.field.path.value] is not None
        super().mark(explicit)
        self.inherit.label = "Use global default" if explicit else "Override here"
        if explicit:
            self.source.update("Override for this object")
        else:
            scope, owner = self.field.state.get_provenance(self.field.path.value)
            self.source.update("Inherited from global defaults")
            self.source.tooltip = f"{owner.__module__}.{owner.__qualname__} · {scope or 'global'}"''', '''        local = self.field.allows_override
        explicit = local and self.field.state.parameters[self.field.path.value] is not None
        super().mark(explicit)
        self.inherit.display = local
        self.inherit.label = "Use global default" if explicit else "Override here"
        if explicit:
            self.source.update("Override for this object")
        else:
            scope, owner = self.field.state.get_provenance(self.field.path.value)
            self.source.update("Inherited from global defaults" if local else "Global setting · applies to every view")
            self.source.tooltip = f"{owner.__module__}.{owner.__qualname__} · {scope or 'global'}"''')
patch('src/toad/object_configuration.py', 'ObjectConfiguration', '''    def shows(self, path: str) -> bool:
        return any(name == path or name.startswith(path + ".") for name in self.editable_paths)

''', '')
Path('.verification/object-settings-sources/fix.plan.json').write_text(json.dumps({'recipes':[{'recipe_id':'discover-settings-at-their-original-scopes','operations':ops}]},indent=2))
