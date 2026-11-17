"""The action family every client offers: what each action is called, when it is offered,
the keys it declares and what it does through the shared host. A client projects the
declared keys into its own bindings; members whose bodies need one toolkit are declared
in that toolkit's modules, as members of this same family."""

from __future__ import annotations

import inspect
from abc import abstractmethod
from collections.abc import Iterator, Mapping
from types import MappingProxyType
from typing import ClassVar, Generic, Self, TypeVar, cast

from agent_comms.nominal.declared_family import (
    DeclaredFamily,
    DeclaredOrder,
    FamilyMeta,
    declared_words,
)
from agent_comms.planning.command import Command
from formbridge.key_declarations import InputMode, KeyDeclaration, KeyDeclarationType

from toad.client.application import ClientApplication
from toad.session_navigation import ChannelsReveal


Context = TypeVar("Context")


class KeyFamilyMeta(FamilyMeta, KeyDeclarationType):
    """A named command family whose classes declare native key overlap."""


class DeclaredAction(KeyDeclaration[Context], Command, DeclaredFamily, Generic[Context],
                     metaclass=KeyFamilyMeta, affix="Action"):
    """Only a client's boundary decodes an external action name. A member declares its
    keys, and its title and docstring are the only text any view shows for it."""

    keys: ClassVar[Mapping[type[InputMode], tuple[str, ...]]] = MappingProxyType({})
    show: ClassVar[bool] = False
    priority: ClassVar[bool] = False
    key_display: ClassVar[str | None] = None
    binding_prefix: ClassVar[str] = ""

    @classmethod
    def default_title(cls) -> str:
        """The class's own derived name, never its declared_name: views show what a member does."""
        return declared_words(cls.__name__.removesuffix(cls._family_affix)).replace("_", " ").capitalize()

    @classmethod
    def declarations(cls) -> Iterator[type[Self]]:
        """The native registry filters by this class, so each member is one of its own."""
        return cast("Iterator[type[Self]]", super().declarations())

    @classmethod
    def summary(cls) -> str:
        """The nearest docstring a member declares; the family roots document code, not keys."""
        root = cls.family_root
        return next((inspect.cleandoc(base.__doc__) for base in cls.__mro__
                     if issubclass(base, root) and base is not root and base.__doc__), "")

    @classmethod
    def binding_name(cls) -> str:
        return cls.binding_prefix + cls.declared_name

    @classmethod
    def command_for_key(cls, mode: type[InputMode], key: str) -> Self:
        return cls()

    @classmethod
    def refine_binding[Binding](cls, binding: Binding) -> Binding:
        """A family whose bindings carry more of its declaration completes them here."""
        return binding

    @classmethod
    def exclusive_claims[Binding](cls, bindings: tuple[Binding, ...]) -> tuple[Binding, ...]:
        """The keys this member claims against every other scope's: none unless it says so."""
        return ()

    def __call__(self, context: Context) -> object:
        return self.apply(context)

    @classmethod
    def parse(cls, parameters: tuple[object, ...]):
        if parameters:
            raise ValueError(f"{cls.declared_name} takes no parameters")
        return cls()

    @classmethod
    def require_unwritten(cls, name: str, writers: tuple[type, ...]) -> None:
        """A generated dispatcher may not replace an action a class wrote: a member whose apply
        calls that action would then call itself."""
        if writers:
            raise TypeError(f"{cls.__qualname__} would replace {writers[0].__qualname__}.{name}")

    @classmethod
    def offered(cls, context: Context) -> Iterator[Self]:
        """What the menu and the palette offer for this member: itself, where it is available."""
        command = cls()
        if command.available(context):
            yield command

    def label(self, context: Context) -> str:
        """A state-dependent title overrides this; every other member shows its title."""
        return self.title

    def available(self, context: Context) -> bool | None:
        return True

    def engine_boundary(self, editor: object) -> bool:
        """An external engine offers this action at its key; only an EngineKey member is asked."""
        return False

    def key_available(self, context: Context) -> bool | None:
        """Keyboard scope may be narrower than menu/palette command availability."""
        return self.available(context)

    @abstractmethod
    def apply(self, context: Context) -> object: ...


class System:
    """Only its key reaches the action: no menu, palette or key panel shows it."""

    system: ClassVar[bool] = True

    @classmethod
    def offered(cls, context: object) -> Iterator[Self]:
        return iter(())


class YieldingKey:
    """An application key that any binding closer to the focus replaces: it answers only
    where nothing local claims the key, so the claim is no conflict."""

    priority = False

    @classmethod
    def exclusive_claims[Binding](cls, bindings: tuple[Binding, ...]) -> tuple[Binding, ...]:
        return ()


class ReplacesFrameworkAction:
    """A member declared to stand in for one of the toolkit's own actions (Screen.action_dismiss,
    App.action_quit): replacing that written action is its purpose."""

    @classmethod
    def require_unwritten(cls, name: str, writers: tuple[type, ...]) -> None:
        pass


class MenuPlace(DeclaredOrder):
    """Where a member sits in the menu and the palette; within a place, declaration order."""


class InMenu(MenuPlace):
    """The menu's body."""


class LastInMenu(MenuPlace):
    """After every other member, wherever it is declared."""


class ApplicationAction(DeclaredAction[ClientApplication], InMenu, affix="Action"):
    """Declared application shortcuts resolve before an editor takes the key."""

    binding_prefix = "app."
    priority = True

    @classmethod
    def exclusive_claims[Binding](cls, bindings: tuple[Binding, ...]) -> tuple[Binding, ...]:
        return bindings

    @classmethod
    def menu(cls, app: ClientApplication) -> tuple[tuple[ApplicationAction, str], ...]:
        """Every offered member with show=True under its label, by menu place then in
        declaration order. Members without show=True are keybinding/command-palette only;
        they never appear in the burger menu, so Qt and Textual show exactly the same list
        (whichever members they've imported), and debug poke-actions never leak into the
        user menu."""
        return tuple((command, command.label(app))
                     for member in sorted(cls.members_with(cls), key=MenuPlace.position_of)
                     if member.show
                     for command in member.offered(app))


# Declaration order is the order of the menu and the palette.
class NewSessionAction(ApplicationAction):
    """Start this launch's session: its attached agent's, or a native thread.

    Both frontends fire this (Textual's `StartSessionButton` and Qt's Welcome
    `NewSessionButton`): the body lives on the ClientApplication so one owner
    answers the "new session" intent regardless of toolkit. The Textual welcome
    screen still binds its `n` key through its own `WelcomeStartSession`
    action, which forwards here."""

    show = True

    async def apply(self, app: ClientApplication) -> None:
        navigation = app.session_navigation
        await app.agent_binding.start_session(navigation, navigation.selected_project())


class NewThreadAction(ApplicationAction):
    """Start a thread in the selected project."""

    show = True

    async def apply(self, app: ClientApplication) -> None:
        navigation = app.session_navigation
        navigation.open_thread_form(navigation.selected_project())


class ChannelsAction(ApplicationAction):
    """Reveal channels and focus the selected session."""

    keys = {InputMode: ("ctrl+s",)}
    show = True

    async def apply(self, app: ClientApplication) -> None:
        app.run_operation(ChannelsReveal, app.session_navigation.reveal)


class DirectMessagesAction(ApplicationAction):
    """Open the most recently selected direct conversation."""

    keys = {InputMode: ("ctrl+shift+d",)}
    show = True

    async def apply(self, app: ClientApplication) -> None:
        app.session_navigation.direct_messages()


class QuitAction(LastInMenu, ReplacesFrameworkAction, ApplicationAction):
    """Save preferences and quit the application."""

    keys = {InputMode: ("ctrl+q",)}
    show = True

    async def apply(self, app: ClientApplication) -> None:
        app.application.quit()
