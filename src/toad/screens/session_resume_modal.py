from datetime import UTC, datetime
from agent_comms.nominal.field_codec import RecordedTimestamp

from textual import containers, getters, on, widgets
from textual.app import ComposeResult
from textual.widgets._markdown import MarkdownH1
from toad.native_layout import NativeLayout
from toad.screens.modal import DismissibleScreen

from toad.db import DB, Session

HELP = """\
# Session Resume

Pick a session to resume.
"""


class ResumeHeading(NativeLayout, MarkdownH1):
    def apply_native_layout(self) -> None:
        self.styles.margin = (1, 0)


class ResumeHelp(widgets.Markdown):
    BLOCKS = widgets.Markdown.BLOCKS | {f"h{ResumeHeading.LEVEL}": ResumeHeading}


class ResumeWarning(NativeLayout, widgets.Static):
    def apply_native_layout(self) -> None:
        self.styles.padding = (0, 1)
        self.styles.margin = (0, 0, 1, 1)


class ResumeFrame(NativeLayout, containers.VerticalGroup):
    def apply_native_layout(self) -> None:
        self.styles.margin = (2, 4, 1, 4)
        self.styles.padding = (0, 1, 0, 0)
        self.styles.max_width = 100
        self.styles.height = "auto"


class ResumeTableContainer(NativeLayout, containers.Center):
    def apply_native_layout(self) -> None:
        self.styles.height = "auto"
        self.styles.padding = (0, 0, 0, 1)


class ResumeTable(NativeLayout, widgets.DataTable):
    def apply_native_layout(self) -> None:
        self.styles.width = "1fr"
        self.styles.height = 12


class ResumeButtons(NativeLayout, containers.HorizontalGroup):
    def apply_native_layout(self) -> None:
        self.styles.margin = (1, 0, 0, 0)
        self.styles.align = ("right", "top")


class SessionResumeModal(NativeLayout, DismissibleScreen[Session]):
    """Dialog to select a session to resume."""

    CSS_PATH = "session_resume_modal.tcss"

    session_table = getters.query_one("#sessions", ResumeTable)

    def apply_native_layout(self) -> None:
        self.styles.align = ("center", "middle")

    def compose(self) -> ComposeResult:
        with ResumeFrame(id="container"):
            yield ResumeHelp(HELP)
            yield ResumeWarning(
                "⚠ Not all ACP agents currently support resume",
                classes="warning",
            )
            with ResumeTableContainer(id="table-container"):
                yield ResumeTable(id="sessions", cursor_type="row")
            with ResumeButtons(id="buttons"):
                yield widgets.Button(
                    "Resume", id="resume", variant="primary", disabled=True
                )
                yield widgets.Button("Cancel", id="cancel")

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

    async def dissmiss_with_session(self, row_key_value: str) -> Session | None:
        session_id = int(row_key_value)
        db = DB()
        session = await db.session_get(session_id)
        self.dismiss(session)

    @on(widgets.Button.Pressed, "#resume")
    async def on_resume_button(self) -> None:
        table = self.session_table
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        if row_key is None or row_key.value is None:
            return
        await self.dissmiss_with_session(row_key.value)

    @on(widgets.Button.Pressed, "#cancel")
    def on_cancel_button(self) -> None:
        self.dismiss()

    @on(widgets.DataTable.RowHighlighted)
    def on_data_table_row_highlighted(self) -> None:
        self.query_one("#resume").disabled = False

    @on(widgets.DataTable.RowSelected)
    async def on_data_table_row_selected(
        self, event: widgets.DataTable.RowSelected
    ) -> None:
        if event.row_key is None or event.row_key.value is None:
            return
        await self.dissmiss_with_session(event.row_key.value)


if __name__ == "__main__":
    from textual.app import App, ComposeResult

    class TApp(App):
        def on_mount(self):
            self.push_screen(SessionResumeModal())

    app = TApp()
    app.run()
