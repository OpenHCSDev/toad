"""Textual-facing: an error Toad shows keeps its text verbatim; markup brackets in it never crash the app."""

from support.applications import record_notifications


async def test_an_error_with_markup_brackets_is_shown_verbatim(workspace):
    async with workspace.app(size=(110, 30)) as ui:
        app, pilot = ui.textual
        record_notifications(app)
        app.show_error(ValueError("bad [bold] value"), "Settings")
        await pilot.pause()
        # Toad presents notifications through TerminalAttention, which parsed markup and crashed on brackets.
        assert app.is_running
        note = list(app._notifications)[-1]
        assert (note.title, note.message, note.severity, note.markup) == ("Settings", "bad [bold] value", "error", False)
