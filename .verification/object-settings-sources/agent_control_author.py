import json
from pathlib import Path
r=Path.cwd();ops=[]
def patch(f,t,o,n):ops.append(dict(operation='patch_target',file_path=str(r/f),target_qualname=t,replacements=[dict(old_source=o,new_source=n)]))
patch('tests/textual/test_sidebar_projection.py','test_view_menu_discovers_settings_and_keeps_each_objects_state', '''        native_menu = native_bar.query_one(PanelMenu)
        relationships =''','''        native_menu = native_bar.query_one(PanelMenu)
        from acp.schema import SetSessionConfigOptionResponse
        from support.agents import AppAgents
        from toad.configured_view import AgentProperties
        from toad.widgets.model_switcher import SessionForm
        agent = AppAgents(app).detached_agent('sidebar-settings')
        native.conversation.bind_agent(agent)
        agent.configuration.receive(SetSessionConfigOptionResponse.model_validate({'configOptions': [
            {'id': 'sample-budget', 'name': 'Budget', 'type': 'boolean', 'currentValue': True},
        ]}).config_options)
        agent_entry = next(entry for entry in native_menu.entries if isinstance(entry.widget, AgentProperties))
        native_menu.picker.value = agent_entry
        await ui.until(lambda: agent_entry.widget.is_mounted and bool(agent_entry.widget.query(SessionForm)),
                       why='the actual advertised session form')
        await ui.until(lambda: agent_entry.widget.form.represents(agent.configuration),
                       why='new advertisements replace the original fields')
        assert agent_entry.widget.form.prompt is native.conversation.prompt
        assert 'Budget' in {row.field.label for row in agent_entry.widget.form.values.values()}
        agent.configuration.receive(SetSessionConfigOptionResponse.model_validate({'configOptions': [
            {'id': 'sample-budget', 'name': 'Budget', 'type': 'boolean', 'currentValue': False},
            {'id': 'new-setting', 'name': 'New setting', 'type': 'boolean', 'currentValue': True},
        ]}).config_options)
        await ui.until(lambda: agent_entry.widget.form.represents(agent.configuration),
                       why='the sidebar follows the source update')
        assert 'New setting' in {row.field.label for row in agent_entry.widget.form.values.values()}
        relationships =''')
# FieldView already admits every visible declaration; retain its inherited answer.
Path('.verification/object-settings-sources/agent-control.plan.json').write_text(json.dumps({'recipes':[{'recipe_id':'selected-session-advertisement-control','operations':ops}]},indent=2))
