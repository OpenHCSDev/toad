import ast,json
from pathlib import Path
r=Path('/home/ts/wt/codex-live--P181--toad/src/toad');ops=[]
def patch(f,t,o,n):ops.append(dict(operation='patch_target',file_path=str(r/f),target_qualname=t,replacements=[dict(old_source=o,new_source=n)]))
def imp(f,s):ops.append(dict(operation='ensure_import',file_path=str(r/f),import_source=s))
s=(r/'widgets/comms_menu.py').read_text();n=next(n for n in ast.parse(s).body if isinstance(n,ast.FunctionDef) and n.name=='show_target_menu')
patch('widgets/comms_menu.py','show_target_menu',ast.get_source_segment(s,n),'''class ActionMenu(ContextMenu[Callable[[], object]]):
    """The selected row carries the actual operation; there is no second lookup table."""

    @classmethod
    def show(cls, screen, anchor: Region, title: str, items):
        return super().show(screen, anchor, title, items, callback=cls.run_action)

    @staticmethod
    async def run_action(action):
        if action is not None:
            await invoke(action)
''')
imp('widgets/comms_menu.py','from textual._callback import invoke')
patch('target_commands.py','TargetContext.show_menu','from toad.widgets.comms_menu import show_target_menu','from toad.widgets.comms_menu import ActionMenu')
patch('target_commands.py','TargetContext.show_menu','''            show_target_menu(selected_screen, Region.from_offset(offset, (0, 0)), self.title,
                [(command.command.removeprefix('/'), command.label(self)) for command in choices],
                {command.command.removeprefix('/'): partial(self.execute_menu, sidebar, command)
                 for command in choices})''','''            ActionMenu.show(selected_screen, Region.from_offset(offset, (0, 0)), self.title,
                [(partial(self.execute_menu, sidebar, command), command.label(self))
                 for command in choices])''')
patch('widgets/thread_comms.py','toad.widgets.thread_comms','from toad.widgets.comms_menu import show_target_menu','from toad.widgets.comms_menu import ActionMenu')
patch('widgets/thread_comms.py','ThreadCommsSidebar.show_row_menu','''        items = [("open", "Open")] if row.available else []
        items.append(("copy", "Copy name"))
        show_target_menu(
            self.screen,
            Region.from_offset(offset, (0, 0)),
            target,
            items,
            {"open": open_selected, "copy": lambda: self.app.copy_to_clipboard(target)},
        )''','''        items = [(open_selected, "Open")] if row.available else []
        items.append((lambda: self.app.copy_to_clipboard(target), "Copy name"))
        ActionMenu.show(self.screen, Region.from_offset(offset, (0, 0)), target, items)''')
patch('widgets/context_explorer.py','ContextCorrect.apply','from toad.widgets.comms_menu import show_target_menu','from toad.widgets.comms_menu import ActionMenu')
patch('widgets/context_explorer.py','ContextCorrect.apply','''        show_target_menu(
            self.screen,
            self.region,
            "Correct original answer",
            [(answer.declared_name, answer.public_title()) for answer in answers],
            {answer.declared_name: partial(self._correct, explorer, model, answer) for answer in answers},
        )''','''        ActionMenu.show(
            self.screen, self.region, "Correct original answer",
            [(partial(self._correct, explorer, model, answer), answer.public_title())
             for answer in answers],
        )''')
patch('configured_view.py','toad.configured_view','from toad.widgets.comms_menu import ContextMenu','from toad.widgets.comms_menu import ActionMenu')
patch('configured_view.py','ConfiguredView.configuration_menu','''        ContextMenu.show(self.screen, Region.from_offset(event.screen_offset, (0, 0)),
                         self.display_name, [(self.open_configuration, "Properties…")],
                         callback=lambda chosen: chosen() if chosen is not None else None)''','''        ActionMenu.show(self.screen, Region.from_offset(event.screen_offset, (0, 0)),
                        self.display_name, [(self.open_configuration, "Properties…")])''')
patch('project_link.py','ProjectFileLink.copy_file','from toad.widgets.comms_menu import ContextMenu','from toad.widgets.comms_menu import ActionMenu')
patch('project_link.py','ProjectFileLink.copy_file','''        ContextMenu.show(widget.screen, Region.from_offset(event.screen_offset, (0, 0)), full_path,
                         [(copy_path, "Copy full path")],
                         callback=lambda chosen: chosen() if chosen is not None else None)''','''        ActionMenu.show(widget.screen, Region.from_offset(event.screen_offset, (0, 0)), full_path,
                        [(copy_path, "Copy full path")])''')
Path('/home/ts/.cache/agent-scratch/codex-latency/p192-action-menus.plan.json').write_text(json.dumps({'recipes':[dict(recipe_id='menu-rows-own-their-actual-operation',operations=ops)]},indent=2))
