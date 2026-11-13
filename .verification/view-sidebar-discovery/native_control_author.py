import json
from pathlib import Path
p=Path('tests/textual/test_sidebar_projection.py').resolve()
old="""        await ui.select_tab(original)


"""
new="""        view.open_configuration()
        await ui.step()
        dialog = app.screen
        assert all(entry.widget.field.state is state for entry in dialog.form.entries)
        await ui.until(lambda: bool(dialog.query(ObjectValueView)), why='the shared context editor')
        dialog.dismiss_control()
        await ui.step()
        await ui.select_tab(original)
        native = app.workspace_sessions.require(original)
        workspace.thread('panel-owner')
        await workspace.bind(native, 'panel-owner')
        native_bar = await ui.revealed(native.thread_sidebar)
        native_menu = native_bar.query_one(PanelMenu)
        relationships = next(entry for entry in native_menu.entries
                             if isinstance(entry.widget, ThreadCommsSidebar))
        native_menu.picker.value = relationships
        await ui.until(lambda: relationships.widget.is_mounted, why='the native relationship panel')
        assert relationships.widget.panel_visible
        relationships.widget._visible()
        settings_entry = next(entry for entry in native_menu.entries
                              if isinstance(entry.widget, ObjectProperties))
        native_menu.picker.value = settings_entry
        await ui.until(lambda: not relationships.widget.panel_visible, why='the hidden native panel')


"""
plan={'recipes':[{'recipe_id':'exercise-native-panel-and-context-lifecycle','operations':[dict(operation='patch_target',file_path=str(p),target_qualname='test_view_menu_discovers_settings_and_keeps_each_objects_state',replacements=[dict(old_source=old.rstrip(),new_source=new.rstrip())])]}]}
Path('.verification/view-sidebar-discovery/native-control.plan.json').write_text(json.dumps(plan,indent=2))
