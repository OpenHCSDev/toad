from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from agent_comms.nominal.field_codec import RecordedTimestamp

from textual import containers, getters, on, widgets
from textual.app import ComposeResult
from textual.css.native import Keyword, NativeDeclaration, TextVariable, Variable
from textual.css.styles import Styles
from textual.widgets._markdown import MarkdownH1
from ui_theme.scheme import WarningColour

from toad.widgets.acting_button import ConfirmButton, Confirms, DismissButton
from toad.native_style import (
    AutoHeight,
    FillWidth,
    SidePadding,
    SpacedAbove,
    SpacedAround,
)
from toad.screens.modal import CenteredScreen, DismissibleScreen, ModalFrame


from toad.app import ToadApp
from toad.core import session_requests
from toad.db import DB, Session

HELP = """\
# Session Resume

Pick a session to resume.
"""


class ResumeHeading(SpacedAround, MarkdownH1):
    """Its look is its bases."""


class ResumeHelp(widgets.Markdown):
    BLOCKS = widgets.Markdown.BLOCKS | {f"h{ResumeHeading.LEVEL}": ResumeHeading}


class ResumeWarning(SidePadding, widgets.Static):
    native_theme = (
        NativeDeclaration.of(Styles.border, Keyword("round"), Variable(WarningColour.name)),
        NativeDeclaration.of(Styles.color, TextVariable(WarningColour.name)),
    )

    def apply_native_layout(self) -> None:
        self.styles.margin = (0, 0, 1, 1)


class ResumeTableContainer(AutoHeight, containers.Center):
    def apply_native_layout(self) -> None:
        self.styles.padding = (0, 0, 0, 1)


class ResumeTable(FillWidth, widgets.DataTable):
    def apply_native_layout(self) -> None:
        self.styles.height = 12


class ResumeButtons(SpacedAbove, containers.HorizontalGroup):
    def apply_native_layout(self) -> None:
        self.styles.align = ("right", "top")


class ResumeButton(ConfirmButton):
    """Resumes the highlighted session."""


class ResumeChoice(ABC):
    """What closing the resume dialog asks the app to do."""

    @abstractmethod
    def resume(self, app: ToadApp) -> None: ...


@dataclass(frozen=True)
class ResumeSession(ResumeChoice):
    session: Session

    def resume(self, app: ToadApp) -> None:
        app.session_navigation.events.publish(
            session_requests.LaunchAgent(
                self.session.agent_identity,
                self.session.agent_session_id,
                pk=self.session.id,
            )
        )


class NoResume(ResumeChoice):
    """The dialog was cancelled."""

    def resume(self, app: ToadApp) -> None:
        pass


class SessionResumeModal(Confirms, CenteredScreen, DismissibleScreen[ResumeChoice]):
    """Dialog to select a session to resume."""

    session_table = getters.query_one(ResumeTable)
    resume_button = getters.query_one(ResumeButton)

    def compose(self) -> ComposeResult:
        with ModalFrame():
            yield ResumeHelp(HELP)
            yield ResumeWarning(
                "⚠ Not all ACP agents currently support resume",
            )
            with ResumeTableContainer():
                yield ResumeTable(cursor_type="row")
            with ResumeButtons():
                yield ResumeButton("Resume", variant="primary", disabled=True)
                yield DismissButton("Cancel")

    @classmethod
    def friendly_time_ago(cls, past: RecordedTimestamp) -> str:
        """Present a time the session store recorded; Core requires its UTC offset."""
        total_seconds = (datetime.now(UTC) - past.at).total_seconds()

        # Less than 1 minute
        if total_seconds < 60:
            return "just now"

        # Less than 1 hour (3600 seconds)
        if total_seconds < 3600:
            minutes = int(total_seconds // 60)
            return f"{minutes} minute{'s' if minutes != 1 else ''} ago"

        # Less than 24 hours (86400 seconds)
        if total_seconds < 86400:
            hours = int(total_seconds // 3600)
            return f"{hours} hour{'s' if hours != 1 else ''} ago"

        # 24 hours or more - return as local time
        return past.at.astimezone().strftime("%c")

    async def on_mount(self) -> None:
        table = self.session_table
        table.add_columns("Agent", "Session", "Created", "Last Used", "Path")
        db = DB()
        sessions = await db.session_get_recent()
        # The rows are these sessions; choosing one needs no second read.
        self._sessions = {str(session.id): session for session in sessions}
        for session in sessions:
            cwd = "".join(map(str, session.meta_json.cwd.present()))

            table.add_row(
                session.agent,
                session.title,
                self.friendly_time_ago(session.created_at),
                self.friendly_time_ago(session.last_used),
                cwd,
                key=str(session.id),
            )

    def dismiss_control(self) -> None:
        self.dismiss(NoResume())

    def choose_session(self, row_key_value: str) -> None:
        self.dismiss(ResumeSession(self._sessions[row_key_value]))

    async def confirm(self) -> None:
        table = self.session_table
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        if row_key is None or row_key.value is None:
            return
        self.choose_session(row_key.value)

    @on(widgets.DataTable.RowHighlighted)
    def on_data_table_row_highlighted(self) -> None:
        self.resume_button.disabled = False

    @on(widgets.DataTable.RowSelected)
    async def on_data_table_row_selected(
        self, event: widgets.DataTable.RowSelected
    ) -> None:
        if event.row_key is None or event.row_key.value is None:
            return
        self.choose_session(event.row_key.value)


if __name__ == "__main__":
    from textual.app import App, ComposeResult

    class TApp(App):
        def on_mount(self):
            self.push_screen(SessionResumeModal())

    app = TApp()
    app.run()
