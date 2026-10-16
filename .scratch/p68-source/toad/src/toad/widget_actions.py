"""Project declared actions into Textual's native action method namespace."""
from functools import partialmethod


class DeclaredWidgetActions:
    """One family supplies both native dispatch and dynamic availability."""

    def __init_subclass__(cls, **kwargs):
        if "ACTIONS" not in cls.__dict__:
            super().__init_subclass__(**kwargs)
            return
        actions = cls.ACTIONS
        cls.BINDINGS = [*cls.__dict__.get("BINDINGS", ()),
                        *(binding for declaration in actions.members_with(actions)
                          for binding in declaration.bindings())]
        for declaration in actions.members_with(actions):
            setattr(cls, f"action_{declaration.declared_name}",
                    partialmethod(cls._run_declared_action, declaration))
        super().__init_subclass__(**kwargs)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        try:
            declaration = self.ACTIONS.decode(action)
        except ValueError:
            return super().check_action(action, parameters)
        return declaration.parse(parameters).available(self)

    async def _run_declared_action(self, declaration, *parameters) -> None:
        command = declaration.parse(parameters)
        if command.available(self):
            await command.apply(self)
