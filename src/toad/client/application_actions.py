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
from formbridge.key_declarations import InputMode, KeyDeclaration, KeyDeclarationType, TextEntryMode
from formbridge.operations import OperationKind

from toad.client.application import ClientApplication
from toad.client.pending import ActionRunning, awaited
from toad.client.transfers import Transfer
from toad.session_navigation import ChannelsReveal


@awaited(ActionRunning)
class MenuActionRun(OperationKind):
    """One application action chosen from the menu."""


Context = TypeVar("Context")


class DuplicateSavedKey(TypeError):
    """Two key declarations would be saved under one name: raised as the second class is
    created, so the clash fails at import in development and CI, never in a user's toad.json."""


class KeyFamilyMeta(FamilyMeta, KeyDeclarationType):
    """A named command family whose classes declare native key overlap.

    Each member is also the owner of the name a saved keymap stores for it: its class name,
    unless a member whose class name another declaration already uses declares `saved_key`
    in its own body. Names are unique by construction — a second member saved under one
    name raises `DuplicateSavedKey` while it is being created — and none names a module,
    so moving a declaration between modules never unbinds a user's keys."""

    _saved: ClassVar[dict[str, type]] = {}
    _saved_by_identity: ClassVar[dict[str, str]] = {}

    def __init__(cls, name: str, bases: tuple[type, ...], namespace: dict[str, object],
                 **options: object) -> None:
        super().__init__(name, bases, namespace, **options)
        if inspect.isabstract(cls) or cls.declared_name is None:
            return  # a family root or abstract layer: never a saved keymap entry
        key = cls.saved_key_name()
        held = KeyFamilyMeta._saved.get(key)
        if held is not None and (held.__module__, held.__qualname__) != (cls.__module__, cls.__qualname__):
            raise DuplicateSavedKey(
                f"{cls.__module__}.{cls.__qualname__} would be saved in keymaps as {key!r}, "
                f"which already names {held.__module__}.{held.__qualname__}; declare "
                f"`saved_key` in its class body")
        foreign = next((declared for declared in KeyDeclaration._declared
                        if declared.__qualname__ == key and not isinstance(declared, KeyFamilyMeta)
                        and not inspect.isabstract(declared)), None)
        if foreign is not None:
            raise DuplicateSavedKey(
                f"{cls.__module__}.{cls.__qualname__} would be saved in keymaps as {key!r}, "
                f"the name of {foreign.__module__}.{foreign.__qualname__}; declare `saved_key`")
        KeyFamilyMeta._saved[key] = cls
        KeyFamilyMeta._saved_by_identity[KeyDeclaration.qualified(cls)] = key

    def saved_key_name(cls) -> str:
        """The name this member is saved under: declared in its own body, else its class."""
        return cast(str, vars(cls).get("saved_key", cls.__qualname__))

    @staticmethod
    def saved_name_of(identity: str) -> str | None:
        """The saved name of the toad declaration with this identity; None for a command toad
        does not declare (a Textual binding, a formbridge key), which is saved by identity."""
        return KeyFamilyMeta._saved_by_identity.get(identity)

    @staticmethod
    def saved_member(name: str) -> type | None:
        return KeyFamilyMeta._saved.get(name)

    @staticmethod
    def saved_members() -> tuple[type, ...]:
        return tuple(KeyFamilyMeta._saved.values())


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

    # The capability a context must have for this action to run on it. A frontend binds a
    # family's keys only for the members its context has the capability for (`runs_on`), so a
    # member that reaches another toolkit's chrome is never bound there, and running a bound
    # one never has to guess whether its context fits.
    context_capability: ClassVar[type] = object

    @classmethod
    def runs_on(cls, context: object) -> bool:
        return isinstance(context, cls.context_capability)

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
    App.action_quit): replacing that written action is its purpose.

    A mixin listed before the member's family base (a declaration belongs to one family, so it
    cannot subclass DeclaredAction itself). Listed after it, DeclaredAction's own check runs,
    sees the toolkit writer and refuses at class creation: wrong order fails loudly."""

    @classmethod
    def require_unwritten(cls, name: str, writers: tuple[type, ...]) -> None:
        """Only the toolkit's own writers are exempt. An action a toad class wrote is refused here
        as for every declaration: this member's apply would call itself."""
        super().require_unwritten(name, tuple(
            writer for writer in writers if not writer.__module__.startswith("textual.")))


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



class OpensWindow:
    """An application action whose `apply` opens a window over the app: Settings, the team
    board, the keymap, a transfer, the bus switcher. Each frontend presents every such window
    through its one presentation owner (Qt's `PresentedWindow`), so the windows a reader can
    open are this family's members, read wherever all of them must be checked."""


# Declaration order is the order of the menu and the palette.
class NewSessionAction(ApplicationAction):
    """Start this launch's session: its attached agent's, or a native thread."""

    # The docstring is the text every menu and palette shows the reader. Both frontends fire
    # it from the comms sidebar's New Session row while no tab is shown
    # (`NewSessionControl.action`), and Textual's `n` key there (`SoleNewSessionAction`).
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


class OpenBusAction(OpensWindow, ApplicationAction):
    """Connect to this machine's bus or choose another machine."""

    title = "Switch bus (local or remote)"
    keys = {TextEntryMode: ("ctrl+shift+b",)}
    show = True

    async def apply(self, app: ClientApplication) -> None:
        app.open_bus_switcher()


class SettingsAction(OpensWindow, ApplicationAction):
    """Edit persistent application preferences."""

    keys = {TextEntryMode: ("ctrl+comma",)}
    show = True

    async def apply(self, app: ClientApplication) -> None:
        await app.edit_settings()


class ZoomInAction(ApplicationAction):
    """Increase message text size by 10%."""

    title = "Zoom in text"
    keys = {TextEntryMode: ("ctrl+=", "ctrl+plus")}
    show = True

    async def apply(self, app: ClientApplication) -> None:
        app.adjust_message_font_scale(10)


class ZoomOutAction(ApplicationAction):
    """Decrease message text size by 10%."""

    title = "Zoom out text"
    keys = {TextEntryMode: ("ctrl+-",)}
    show = True

    async def apply(self, app: ClientApplication) -> None:
        app.adjust_message_font_scale(-10)


class ResetZoomAction(ApplicationAction):
    """Reset message text size to 100%."""

    title = "Reset text size"
    keys = {TextEntryMode: ("ctrl+0",)}
    show = True

    async def apply(self, app: ClientApplication) -> None:
        app.reset_message_font_scale()


class TeamAction(OpensWindow, ApplicationAction, declared_name="team"):
    """Open the live team board, including teammates' orders and original evidence."""

    keys = {TextEntryMode: ("f2",)}
    show = True

    async def apply(self, app: ClientApplication) -> None:
        await app.open_team_board()


class KeymapAction(OpensWindow, ApplicationAction):
    """Browse keyboard shortcuts and change their keys for each editing mode."""

    keys = {TextEntryMode: ("f1",)}
    show = True

    async def apply(self, app: ClientApplication) -> None:
        await app.open_keymap_browser()


class TransferMenuAction(OpensWindow, ApplicationAction):
    """Export wire history or import a thread through Core."""

    show = True

    def __init__(self, kind: type[Transfer]) -> None:
        self.kind = kind

    @classmethod
    def offered(cls, app: ClientApplication) -> Iterator[Self]:
        yield from (cls(kind) for kind in Transfer.members_with(Transfer))

    def label(self, app: ClientApplication) -> str:
        return self.kind.title

    @classmethod
    def parse(cls, parameters: tuple[object, ...]) -> Self:
        from agent_comms.nominal.field_codec import FieldCodec
        if len(parameters) != 1:
            raise ValueError("transfer_menu requires one declared transfer kind")
        return cls(FieldCodec.decode(type[Transfer], parameters[0]))

    async def apply(self, app: ClientApplication) -> None:
        app.open_transfer(self.kind)


class QuitAction(LastInMenu, ReplacesFrameworkAction, ApplicationAction):
    """Save preferences and quit the application."""

    keys = {InputMode: ("ctrl+q",)}
    show = True

    async def apply(self, app: ClientApplication) -> None:
        app.application.quit()


class NewSessionControl:
    """The comms sidebar's first row, which starts a session: what it says and the action a
    press applies. Textual's `NewSessionButton` and Qt's `NewSessionRow` inherit it. While no
    tab is shown the sidebar holds the window where the welcome page stood, and the row starts
    this launch's session as the welcome's button did (`NewSessionAction`: the attached agent's,
    or a native thread); beside a tab it starts a thread in the selected project."""

    label = "+ New Session"

    @staticmethod
    def action(app: ClientApplication) -> ApplicationAction:
        return NewSessionAction() if app.sidebar_layout.alone else NewThreadAction()

    async def start_session(self, app: ClientApplication) -> None:
        await self.action(app).apply(app)
