import asyncio,json
from pathlib import Path
from objectstate import ObjectStateRegistry
from textual.containers import Vertical
from toad.textual_colours import ThemedApp
from toad.settings_scope import ConversationSettingsScope, ViewSettingsScope
from toad.object_configuration import ObjectConfiguration
from toad.tab_identity.kinds import PreviewTab
from toad.configured_view import ObjectProperties, ObjectConfigurationDialog
from toad.forms.object_configuration import ObjectFormView

DIRECTORY=Path('/home/ts/.cache/agent-scratch/codex-latency/p192-object-control')
DIRECTORY.mkdir(exist_ok=True)
# Every file this control can write is beneath its explicit private directory.
for file in (DIRECTORY/'objects').glob('*.json') if (DIRECTORY/'objects').exists() else ():
    file.unlink()

class Conversation(ConversationSettingsScope,Vertical):
    def __init__(self,defaults):
        super().__init__()
        self.state=ObjectConfiguration(PreviewTab(DIRECTORY/'conversation.txt'),defaults,DIRECTORY,self)
        self.panel=ObjectProperties.whole(self.state)
    @property
    def configuration_state(self):return self.state
    def compose(self):yield self.panel

class FileOwner(ViewSettingsScope):
    @property
    def configuration_state(self): return self.state

class Control(ThemedApp):
    def compose(self):
        self.view=Conversation(self.configuration_state)
        yield self.view

async def main():
    app=Control()
    async with app.run_test(size=(110,40)) as pilot:
        state=app.view.state
        assert 'ui.column_width' in state.editable_paths
        assert 'ui.input.placeholder' in state.editable_paths
        assert 'ui.theme' not in state.editable_paths
        assert state.get_resolved_value('ui.column_width')==100
        app.configuration_state.update_parameter('ui.input.placeholder','Nested live default')
        assert state.get_resolved_value('ui.input.placeholder')=='Nested live default'
        assert state.get_provenance('ui.input.placeholder')[0]==''
        app.configuration_state.update_parameter('ui.column_width',111)
        assert state.get_resolved_value('ui.column_width')==111
        # The sidebar and context form both use the same actual ObjectState.
        dialog=ObjectConfigurationDialog(state)
        assert dialog.form.state is app.view.panel.state is state
        state.field('ui.column_width').edit(111)
        app.configuration_state.update_parameter('ui.column_width',112)
        assert state.get_resolved_value('ui.column_width')==111
        await pilot.pause()
        app.push_screen(dialog)
        await pilot.pause()
        value=dialog.form.values['ui.column_width']
        await value.inherit.act()
        assert state.get_resolved_value('ui.column_width')==112
        assert 'ui.column_width' not in json.loads(state.path.read_text())['values']
        # Both forms paint the same resolved value after reset.
        await pilot.pause()
        assert app.view.panel.values['ui.column_width'].editor.value=='112'
        assert value.editor.value=='112'
        state.field('ui.column_width').edit(125)
        saved=state.path
        assert saved.is_relative_to(DIRECTORY)
        dialog.dismiss_control()
        state.close()
        reopened=ObjectConfiguration(state.identity,app.configuration_state,DIRECTORY,app.view)
        assert reopened.get_resolved_value('ui.column_width')==125
        assert reopened.parameters['ui.column_width']==125
        reopened.close()
        file_owner=FileOwner()
        file_state=file_owner.state=ObjectConfiguration(PreviewTab(DIRECTORY/'file.txt'),app.configuration_state,DIRECTORY,file_owner)
        assert 'ui.column_width' in file_state.editable_paths
        assert 'ui.input.placeholder' not in file_state.editable_paths
        file_state.close()
        print('PASS: live defaults, explicit-equal override, sidebar/context shared edit, reset, original source, persistence, file/conversation scope')
asyncio.run(main())
