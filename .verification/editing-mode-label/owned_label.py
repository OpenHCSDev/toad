import json
from pathlib import Path
r=Path.cwd();f=str(r/'src/toad/widgets/prompt.py');ops=[]
def patch(t,o,n):ops.append(dict(operation='patch_target',file_path=f,target_qualname=t,replacements=[dict(old_source=o,new_source=n)]))
patch('EditingModeLabel','''    """The label follows its own editor throughout this composition's lifetime."""

    def __init__(self, editor: PromptTextArea):
        super().__init__("", markup=False)
        self.editor = editor

    @on(events.Mount)
    def follow_editor(self) -> None:
        self.watch(self.editor, "editing_mode", self.update_mode)
        self.watch(self.editor, "has_focus", self.update_mode)

    def update_mode(self) -> None:
        self.update((self.editor.editing_mode if self.editor.has_focus else Standard()).label)

''','')
patch('PromptTextArea.__init__','''        self.prompt = prompt\n''','''        self.prompt = prompt
        self.editing_mode_label = EditingModeLabel("", markup=False)
''')
patch('PromptTextArea.on_mount','''        self.apply_keyboard_profile()\n''','''        self.apply_keyboard_profile()
        self.call_after_refresh(lambda: self.show_editing_mode(self.editing_mode))
''')
ops.append(dict(operation='insert_before_target',file_path=f,target_qualname='PromptTextArea.apply_keyboard_profile',source='''    def show_editing_mode(self, mode: EditingMode) -> None:
        """The editor owns its label before either widget is mounted."""
        if self.is_mounted:
            self.editing_mode_label.update((mode if self.has_focus else Standard()).label)

    def watch_has_focus(self, focus: bool) -> None:
        self.show_editing_mode(self.editing_mode)

'''))
patch('Prompt.compose','''            yield EditingModeLabel(editor)''','''            yield editor.editing_mode_label''')
Path('.verification/editing-mode-label/owned-label.plan.json').write_text(json.dumps({'recipes':[{'recipe_id':'retain-the-original-editor-label-through-mount-and-mode-updates','operations':ops}]},indent=2))
