"""Textual-facing: an error Toad shows keeps its text verbatim; markup brackets in it never crash the app."""

from pathlib import Path

from support.applications import record_notifications


async def test_an_error_with_markup_brackets_is_shown_verbatim(workspace):
    async with workspace.app(size=(110, 30)) as ui:
        app, pilot = ui.textual
        record_notifications(app)
        with ui.reporting_error():
            app.show_error(ValueError("bad [bold] value"), "Settings")
            await pilot.pause()
        # Toad presents notifications through TerminalAttention, which parsed markup and crashed on brackets.
        assert app.is_running
        note = list(app._notifications)[-1]
        shown, log = note.message.split("\nLog: ")
        assert (note.title, shown, note.severity, note.markup) == ("Settings", "bad [bold] value", "error", False)
        # The saved traceback the notice points to holds the same verbatim text.
        assert "ValueError: bad [bold] value" in Path(log).read_text()
