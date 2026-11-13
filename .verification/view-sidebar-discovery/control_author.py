import json
from pathlib import Path
p=Path('tests/textual/test_sidebar_projection.py').resolve()
s='''async def test_view_menu_discovers_settings_and_keeps_each_objects_state(workspace):
    from toad.configured_view import ObjectProperties
    from toad.forms.object_configuration import ObjectValueView
    from toad.preferences import SETTINGS
    from toad.widgets.side_bar import PanelMenu
    from toad.widgets.thread_comms import ThreadCommsSidebar

    workspace.comms.channels.create_tag('settings')
    preview = workspace.project / 'example.txt'
    preview.write_text('A viewed file\\n')
    async with workspace.app(size=(140, 45)) as ui:
        app, pilot = ui.textual
        original = ui.selected_tab
        channel = await ui.open_channel('#settings', actor=workspace.viewer)
        view = app.workspace_sessions.require(channel)
        bar = await ui.revealed(view.thread_sidebar)
        menu = bar.query_one(PanelMenu)
        assert not bar.query(ThreadCommsSidebar)
        assert menu.entries and all(isinstance(entry.widget, ObjectProperties) for entry in menu.entries)
        assert len(menu.pages) == 1
        state = view.configuration_state
        assert state.identity == app.session_navigation.get(channel).identity
        await ui.until(lambda: bool(menu.query(ObjectValueView)), why='selected settings fields')
        assert 'ui.column_width' in {part.field.path.value for part in menu.query(ObjectValueView)}
        assert menu.region.width and menu.query_one(ObjectValueView).region.height
        ui_entry = menu.picker.value
        other = next(entry for entry in menu.entries if entry is not ui_entry)
        menu.picker.value = other
        await ui.until(lambda: menu.navigation.panel_title == other.title, why='dropdown selection')
        menu.picker.value = ui_entry
        await ui.until(lambda: menu.navigation.panel_title == ui_entry.title, why='returning to settings')
        app.saved_settings.set(SETTINGS.ui.column_width, 83)
        assert state.fields.ui.column_width == 83
        state.field('ui.column_width').edit(91)
        app.saved_settings.set(SETTINGS.ui.column_width, 85)
        assert state.fields.ui.column_width == 91
        state.reset_parameter('ui.column_width')
        assert state.fields.ui.column_width == 85
        file_mode = await ui.open_preview(preview)
        file_view = app.workspace_sessions.require(file_mode)
        file_bar = await ui.revealed(file_view.thread_sidebar)
        file_menu = file_bar.query_one(PanelMenu)
        assert file_view.configuration_state.identity == app.session_navigation.get(file_mode).identity
        assert file_view.configuration_state is not state
        assert not file_bar.query(ThreadCommsSidebar)
        assert len(file_menu.entries) < len(menu.entries)
        await ui.select_tab(channel)
        assert view.thread_sidebar is bar and bar.query_one(PanelMenu) is menu
        assert menu.picker.value is ui_entry
        await ui.select_tab(original)


'''
ops=[dict(operation='insert_before_target',file_path=str(p),target_qualname='FrameApp',source=s)]
Path('.verification/view-sidebar-discovery/control.plan.json').write_text(json.dumps({'recipes':[{'recipe_id':'selected-view-dropdown-control','operations':ops}]},indent=2))
