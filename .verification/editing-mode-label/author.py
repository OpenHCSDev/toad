import json
from pathlib import Path
r=Path.cwd();f=str(r/'src/toad/widgets/prompt.py');ops=[]
def patch(t,o,n):ops.append(dict(operation='patch_target',file_path=f,target_qualname=t,replacements=[dict(old_source=o,new_source=n)]))
patch('EditingModeLabel','''class EditingModeLabel(AutoWidth, OneRow, SidePadding, NoWrap, Label):
    def apply_native_layout''','''class EditingModeLabel(AutoWidth, OneRow, SidePadding, NoWrap, Label):
    """The label follows its own editor throughout this composition's lifetime."""

    def __init__(self, editor: PromptTextArea):
        super().__init__("", markup=False)
        self.editor = editor

    @on(events.Mount)
    def follow_editor(self) -> None:
        self.watch(self.editor, "editing_mode", self.update_mode)
        self.watch(self.editor, "has_focus", self.update_mode)

    def update_mode(self) -> None:
        self.update((self.editor.editing_mode if self.editor.has_focus else Standard()).label)

    def apply_native_layout''')
patch('PromptTextArea.on_mount','''        self.call_after_refresh(lambda: self.show_editing_mode(self.editing_mode))\n''','')
patch('PromptTextArea','''    def show_editing_mode(self, mode: EditingMode) -> None:
        """Away from the box the Standard keys are in force, so the label says STANDARD."""
        if self.is_mounted:
            self.prompt.editing_mode_label.update((mode if self.has_focus else Standard()).label)

    def watch_has_focus(self, focus: bool) -> None:
        self.show_editing_mode(self.editing_mode)

''','')
patch('Prompt.compose','''                yield self.TEXT_AREA_CLASS(prompt=self).data_bind(''','''                editor = self.TEXT_AREA_CLASS(prompt=self).data_bind(''')
patch('Prompt.compose','''                    slash_commands=Prompt.slash_commands,
                )
        yield from self.compose_info_popups()''','''                    slash_commands=Prompt.slash_commands,
                )
                yield editor
        yield from self.compose_info_popups()''')
patch('Prompt.compose','''            yield EditingModeLabel("", markup=False)''','''            yield EditingModeLabel(editor)''')
Path('.verification/editing-mode-label/fix.plan.json').write_text(json.dumps({'recipes':[{'recipe_id':'label-observes-original-editor-without-sibling-mount-queries','operations':ops}]},indent=2))
