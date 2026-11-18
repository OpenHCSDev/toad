"""The terminal's file pickers for a message composer: a file browser that can leave the
project, and the project's path search. Either reads the chosen file through the
composer's shared `attach_path`; Escape closes either and attaches nothing."""

from __future__ import annotations

from abc import abstractmethod
from pathlib import Path

from formbridge.key_declarations import TextEntryMode
from textual import events, on
from textual.app import ComposeResult
from textual.widgets import DirectoryTree, Input, Label, OptionList
from textual.widgets.option_list import Option

from toad.client.message_files import MessagePromptComposer
from toad.client.project_paths import ProjectPathSearch
from toad.screens.modal import CenteredScreen, DismissibleScreen, ModalFrame
from toad.widget_actions import Action, NativeMethodKeys


class FilePickerScreen(CenteredScreen, DismissibleScreen[None]):
    """A picker over the files of one composer's machine, starting at its project."""

    heading: str

    def __init__(self, composer: MessagePromptComposer, root: Path) -> None:
        super().__init__()
        self.composer, self.root = composer, root

    def compose(self) -> ComposeResult:
        with ModalFrame():
            yield Label(self.heading)
            yield from self.compose_picker()

    @abstractmethod
    def compose_picker(self) -> ComposeResult:
        """The picker's own controls, under its title."""

    async def attach(self, path: Path) -> None:
        """The chosen file goes to the composer; the picker closes first."""
        self.dismiss()
        await self.composer.attach_path(path)


class FileBrowserAction(Action, affix="Action"):
    """Keys the file browser answers."""


class ParentFolderAction(FileBrowserAction):
    """Browse the folder above the one shown."""

    keys = {TextEntryMode: ("backspace",)}
    show = True

    def apply(self, tree: FileBrowserTree) -> None:
        tree.path = Path(tree.path).parent


class FileBrowserTree(NativeMethodKeys, DirectoryTree, actions=(FileBrowserAction,)):
    """Every file and folder, not only what git keeps: a file to attach can be anywhere."""


class FileBrowserScreen(FilePickerScreen):
    heading = "Attach a file · enter opens or attaches · backspace goes up · escape closes"

    def compose_picker(self) -> ComposeResult:
        yield FileBrowserTree(self.root)

    @on(DirectoryTree.FileSelected)
    async def file_selected(self, event: DirectoryTree.FileSelected) -> None:
        event.stop()
        await self.attach(event.path)


class PathSearchScreen(ProjectPathSearch, FilePickerScreen):
    heading = "Attach a project file · type to search · enter attaches · escape closes"

    def __init__(self, composer: MessagePromptComposer, root: Path) -> None:
        super().__init__(composer, root)
        self.start_path_search(root)
        self.spellings: list[str] = []

    def compose_picker(self) -> ComposeResult:
        yield Input(compact=True, placeholder="fuzzy search")
        yield OptionList()

    @on(events.Mount)
    async def list_project(self) -> None:
        self.query_one(Input).focus()
        self.spellings = self.spell_paths(await self.scan_paths(add_directories=False))
        await self.rank_paths(self.spellings)
        self.show_paths(self.spellings)

    def show_paths(self, paths: list[str]) -> None:
        options = self.query_one(OptionList)
        options.set_options([Option(path, id=path) for path in paths[:100]])
        options.highlighted = 0

    @on(Input.Changed)
    async def search(self, event: Input.Changed) -> None:
        self.show_paths(await self.ranked(event.value) if event.value else self.spellings)

    @on(Input.Submitted)
    def submit(self, event: Input.Submitted) -> None:
        """Enter in the search attaches the highlighted path, as choosing it does."""
        self.query_one(OptionList).action_select_cursor()

    @on(OptionList.OptionSelected)
    async def option_selected(self, event: OptionList.OptionSelected) -> None:
        await self.attach(self.root / event.option.id)
