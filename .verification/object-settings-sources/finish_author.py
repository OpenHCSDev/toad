import json
from pathlib import Path
r=Path.cwd();ops=[]
def patch(f,t,o,n):
    ops.append(dict(operation='patch_target',file_path=str(r/f),target_qualname=t,replacements=[dict(old_source=o,new_source=n)]))
patch('src/toad/configured_view.py','ConfiguredView.configuration_state','ObjectConfiguration(identity, self.app.saved_settings.state,','ObjectConfiguration(identity, self.app.saved_settings,')
patch('src/toad/object_configuration.py','ObjectConfiguration.__init__','''    def __init__(self, identity: TabIdentity, defaults: ObjectState,
                 directory: Path, owner: SettingsScope) -> None:
        self.identity, self.defaults, self.owner = identity, defaults, owner''','''    def __init__(self, identity: TabIdentity, global_settings: SavedSettings,
                 directory: Path, owner: SettingsScope) -> None:
        self.global_settings = global_settings
        defaults = global_settings.state
        self.identity, self.defaults, self.owner = identity, defaults, owner''')
ops.append(dict(operation='ensure_import',file_path=str(r/'src/toad/object_configuration.py'),import_source='from toad.preferences import SavedSettings'))
patch('src/toad/object_configuration.py','ObjectSettingField.edit','''        return DeclaredField(self.state.defaults, self.path).edit(value)''','''        result = DeclaredField(self.state.defaults, self.path).edit(value)
        self.state.global_settings.save_sync()
        return result''')
patch('tests/textual/test_sidebar_projection.py','test_view_menu_discovers_settings_and_keeps_each_objects_state', '''        assert len(file_menu.entries) < len(menu.entries)''','''        assert tuple(entry.widget.field.path for entry in file_menu.entries) == tuple(
            entry.widget.field.path for entry in menu.entries)
        # The same declarations remain discoverable; the declaring scope owns writes.
        global_field = file_view.configuration_state.field('notifications.enable_sounds')
        assert not global_field.allows_override
        before = app.saved_settings.state.fields.notifications.enable_sounds
        global_field.edit(not before)
        assert app.saved_settings.state.fields.notifications.enable_sounds is not before
        assert state.fields.notifications.enable_sounds is not before
        assert file_view.configuration_state.fields.notifications.enable_sounds is not before
        assert file_view.configuration_state.parameters['notifications.enable_sounds'] is None
        assert app.saved_settings.path().is_file()
        assert len(file_menu.entries) > 3
        notifications = next(entry for entry in file_menu.entries
                             if entry.widget.field.path.value == 'notifications')
        file_menu.picker.value = notifications
        await ui.until(lambda: notifications.widget.is_mounted, why='discovered notifications form')
        await ui.until(lambda: bool(notifications.widget.query(ObjectValueView)), why='global field controls')
        field_view = next(part for part in notifications.widget.query(ObjectValueView)
                          if part.field.path.value == 'notifications.enable_sounds')
        assert not field_view.inherit.display
        assert 'Global setting' in str(field_view.source.render())''')
Path('.verification/object-settings-sources/finish.plan.json').write_text(json.dumps({'recipes':[{'recipe_id':'persist-global-edits-at-the-original-owner','operations':ops}]},indent=2))
