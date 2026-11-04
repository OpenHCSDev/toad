"""A button carries out its own press; the screen never guesses which button posted."""

from abc import abstractmethod

from textual import on
from textual.dom import DOMNode
from textual.widgets import Button

from toad.widget_actions import DismissibleControl


class Confirms(DOMNode):
    """A dialog whose confirm button carries out its purpose."""

    @abstractmethod
    async def confirm(self) -> None: ...


class ActingButton(Button):
    """A button whose press is its own operation; the press stops here."""

    @abstractmethod
    async def act(self) -> None: ...

    @on(Button.Pressed)
    async def pressed(self, event: Button.Pressed) -> None:
        event.stop()
        await self.act()


class DismissButton(ActingButton):
    """Closes the control that contains it."""

    async def act(self) -> None:
        self.query_ancestor(DismissibleControl).dismiss_control()


class ConfirmButton(ActingButton):
    """Carries out the purpose of the dialog that contains it."""

    async def act(self) -> None:
        await self.query_ancestor(Confirms).confirm()
