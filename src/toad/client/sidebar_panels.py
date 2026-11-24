"""Toolkit-neutral sidebar panel metadata.

`PanelSpec` carries the identity + layout fields both frontends need to describe
a panel: `title` (which doubles as the key under which `SidebarState.panels_collapsed`
stores the panel's collapsed state), `flex` (whether the panel keeps room to
grow into on open), the default `collapsed` state used at first mount, and a
stable `id` for CSS/testing selectors. None of these fields carry widget
references, so the spec imports from either frontend. Each frontend subclasses
this and attaches its own widget reference — Textual's `SideBar.Panel` adds
`widget`/`header_control`, Qt's analog holds a `QWidget`.

Keeping the identity fields in one place means both frontends address the same
panel by the same key when they read/write `SidebarState.panels_collapsed` via
its `is_panel_collapsed` / `set_panel_collapsed` accessors — one authority for
whether a panel is open, so the two frontends can never disagree about its state.
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from metaclass_registry import AbstractHooksMeta

if TYPE_CHECKING:
    from formbridge.forms.declared_fields import DeclaredField


from toad.client.lazy_pages import LazyPages
from toad.client.menu_entry import MenuRowDisplay
from toad.client.session_tracker import SidebarState
from toad.thread_actions import ThreadAction


@dataclass(frozen=True)
class PanelSpec:
    title: str
    flex: bool = False
    collapsed: bool = False
    id: str | None = None


class PanelMenuModel[Entry](LazyPages[Entry, object]):
    """A sidebar whose panels are shown one at a time, picked from a list: Textual's
    `PanelMenu` and Qt's `QtPanelMenu` both inherit this. The entries come from the viewed
    object in its order; the pick opens on the entry the sidebar's `SidebarState` last
    remembered, else the first, and each pick is remembered there."""

    entries: tuple[Entry, ...]
    navigation: SidebarState

    @abstractmethod
    def realize_page(self, entry: Entry):
        """Build this entry's page: its header controls over its panel."""

    @abstractmethod
    def entry_identity(self, entry: Entry) -> object:
        """What names this entry across lazy realizations of its panel."""

    def initial_entry(self) -> Entry:
        remembered = self.navigation.panel_identity
        return next((entry for entry in self.entries if self.entry_identity(entry) == remembered),
                    self.entries[0])

    def remember_entry(self, entry: Entry) -> None:
        self.navigation.panel_identity = self.entry_identity(entry)


class ObjectPropertiesPanel:
    """One setting of the viewed object as a settings-pane entry: Textual's `ObjectProperties`
    and Qt's `QtObjectProperties` both inherit this. The field's path names the entry."""

    field: DeclaredField

    @property
    def panel_identity(self) -> object:
        return self.field.path


class SidebarPanelCollapse(metaclass=AbstractHooksMeta):
    """A collapsible sidebar panel's open state, kept in its sidebar's `SidebarState` under
    the panel's title: Textual's `SideBarCollapsible` and Qt's `QtSidebarPanelFrame` both
    inherit this, so both frontends read and write the one record."""

    @property
    @abstractmethod
    def panel_title(self) -> str: ...

    @property
    @abstractmethod
    def panel_state(self) -> SidebarState: ...

    def stored_collapsed(self, default: bool) -> bool:
        return self.panel_state.is_panel_collapsed(self.panel_title, default)

    def record_collapsed(self, collapsed: bool) -> None:
        self.panel_state.set_panel_collapsed(self.panel_title, collapsed)


class SidebarPanelColumn[Entry](metaclass=AbstractHooksMeta):
    """A sidebar's scrolling column of collapsible panels: Textual's `SidebarViewport` and
    Qt's `QtSidebarPanels` both inherit this. Each entry becomes one collapsible framing its
    panel, opened as the sidebar's `SidebarState` last left it (else as the panel declares);
    an open flex panel takes the column's spare room."""

    @abstractmethod
    def entry_panel(self, entry: Entry) -> PanelSpec:
        """The panel spec an entry declares."""

    @abstractmethod
    def panel_frame(self, entry: Entry, collapsed: bool):
        """This frontend's collapsible around the entry's panel, opened or not."""

    def panel_frames(self, entries, navigation: SidebarState) -> tuple:
        frames = []
        for entry in entries:
            panel = self.entry_panel(entry)
            frames.append(self.panel_frame(entry, navigation.is_panel_collapsed(panel.title, panel.collapsed)))
        return tuple(frames)

    @staticmethod
    def claims_room(panel: PanelSpec, collapsed: bool) -> bool:
        return panel.flex and not collapsed


class ActionPropertiesPanel:
    """One backend configuration operation as a settings-pane entry: Textual's
    `ActionProperties` and Qt's `QtActionProperties` both inherit this. The operation's
    declaration names the entry, and Apply submits through the original guarded writer."""

    context: object
    definition: object

    @property
    def panel_identity(self) -> object:
        return self.definition.declaration

    async def handle_submission(self, arguments) -> None:
        await ThreadAction.submit(self.context, self.definition, arguments)


class ViewActionsPanel(MenuRowDisplay):
    """The viewed object's right-click options as a settings-pane entry: Textual's
    `ViewActions` and Qt's `QtViewActions` both inherit this and render the exact
    `MenuEntry` list `ViewSettingsOwner.view_menu_entries` reads from the declared
    menu owners."""

    panel_spec: ClassVar[PanelSpec] = PanelSpec(title="Actions", flex=True, id="view-actions")
    panel_identity: ClassVar[object] = "view-actions"
