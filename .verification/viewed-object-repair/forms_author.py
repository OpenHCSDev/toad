import json
from pathlib import Path
root=Path.cwd();ops=[]
def patch(f,t,o,n):ops.append(dict(operation='patch_target',file_path=str(root/f),target_qualname=t,replacements=[dict(old_source=o,new_source=n)]))
def insert(f,t,s):ops.append(dict(operation='insert_before_target',file_path=str(root/f),target_qualname=t,source=s))
def imp(f,s):ops.append(dict(operation='ensure_import',file_path=str(root/f),import_source=s))
f='src/toad/widgets/comms_command_dialog.py'
imp(f,'from abc import abstractmethod')
imp(f,'from textual.containers import Vertical')
imp(f,'from toad.widget_actions import DismissibleControl')
patch(f,'CommandDialog','class CommandDialog(Confirms, ShadedScreen, CenteredScreen, DismissibleScreen[dict[str, str | None]], actions=(ApplyCommandAction,)):','class CommandForm(Confirms, DismissibleControl, Vertical, actions=(ApplyCommandAction,)):\n    """One backend operation, embedded in a panel or presented as a dialog."""')
# Replacing the whole declaration first renames its nested targets for the following recipe.
Path('.verification/viewed-object-repair/form-base.plan.json').write_text(json.dumps({'recipes':[{'recipe_id':'name-the-shared-backend-form','operations':ops}]},indent=2))
ops=[]
patch(f,'CommandForm.compose','''        with CommandBox():
            yield CommandTitle(f"{self.definition.label} — {self.target}", markup=False)
            with CommandFormScroll():
                yield CommandConfirmation('', markup=False)
                yield self.form
                yield CommandConfirmed('I confirm this operation')
            with CommandButtons():
                yield ApplyCommandButton('Apply', variant='primary')
                yield CancelCommandButton('Cancel')''','''        yield CommandTitle(f"{self.definition.label} — {self.target}", markup=False)
        with CommandFormScroll():
            yield CommandConfirmation('', markup=False)
            yield self.form
            yield CommandConfirmed('I confirm this operation')
        with CommandButtons():
            yield ApplyCommandButton('Apply', variant='primary')
            yield CancelCommandButton('Cancel')''')
patch(f,'CommandForm.confirm','self.dismiss(arguments)','await self.submit(arguments)')
insert(f,'CommandForm.confirm','''    @abstractmethod
    async def submit(self, arguments: dict[str, str | None]) -> None: ...

    def finish(self) -> None:
        self.form.finish()

    def dismiss_control(self) -> None:
        """An embedded form discards its draft without closing the containing view."""
        for path in self.state.parameters:
            self.state.reset_parameter(path)

''')
patch(f,'CatalogFieldSelection.connect_provider','self.editor.query_ancestor(CommandDialog)','self.editor.query_ancestor(CommandForm)')
patch(f,'ApplyCommandAction.apply','context: CommandDialog','context: CommandForm')
# Native insertion after the complete form using a module target append operation in the next plan.
ops.append(dict(operation='insert_after_target',file_path=str(root/f),target_qualname='CommandForm',source='''class CommandDialog(CommandForm, ShadedScreen, CenteredScreen, DismissibleScreen[dict[str, str | None]]):
    """The shared operation form in its modal presentation."""

    def compose(self) -> ComposeResult:
        with CommandBox():
            yield from super().compose()

    async def submit(self, arguments: dict[str, str | None]) -> None:
        self.dismiss(arguments)

    def dismiss_control(self) -> None:
        self.dismiss(None)
'''))
f='src/toad/thread_actions.py'
# Existing lazy import is moved to a module declaration; target_commands remains guarded annotation only.
imp(f,'from toad.widgets.comms_command_dialog import CommandDialog')
patch(f,'ThreadAction.collect','''        from toad.widgets.comms_command_dialog import CommandDialog

''','')
old='''            def prepare():
                ctx.current()
                return TargetEdit(declaration=definition.declaration,
                    target=definition.declaration.selected_targets(ctx.selection),
                    arguments=arguments, confirmed=bool(definition.edited(arguments).confirmation),
                    channel=definition.channels, project=ctx.project)
            request = await ctx.app.preparation.run_thread(prepare)
            ctx.app.thread_actions.invoke(cls(definition, request, ctx), ctx.title,
                                         source_root=ctx.observed.root)'''
patch(f,'ThreadAction.collect',old,'''            await cls.submit(ctx, definition, arguments)''')
insert(f,'ThreadAction.collect','''    @classmethod
    async def submit(cls, ctx, definition, arguments):
        """Both presentations execute through the original guarded target writer."""
        def prepare():
            ctx.current()
            return TargetEdit(declaration=definition.declaration,
                target=definition.declaration.selected_targets(ctx.selection),
                arguments=arguments, confirmed=bool(definition.edited(arguments).confirmation),
                channel=definition.channels, project=ctx.project)
        request = await ctx.app.preparation.run_thread(prepare)
        ctx.app.thread_actions.invoke(cls(definition, request, ctx), ctx.title,
                                     source_root=ctx.observed.root)

''')
f='src/toad/forms/editors.py'
patch(f,'SelectEditor.control_arguments','"allow_blank": not listed','"allow_blank": True')
f='src/toad/forms/object_configuration.py'
patch(f,'ResetSettingButton.act','self.field.reset()','self.field.reset()\n        self.query_ancestor(ObjectValueView).editor.feedback = ""')
Path('.verification/viewed-object-repair/forms.plan.json').write_text(json.dumps({'recipes':[{'recipe_id':'share-the-original-command-editor-and-writer','operations':ops}]},indent=2))
