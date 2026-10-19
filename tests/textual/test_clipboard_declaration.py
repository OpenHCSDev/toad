"""Textual-facing: a clipboard transport declared in one place is chosen by name and copies through Textual's app clipboard."""

from textual.app import App

from toad.clipboard import Clipboard


def test_new_clipboard_case_is_declared_and_uses_common_copy_contract():
    class FutureClipboard(Clipboard):
        def publish(self, app, text):
            app.title = text
            return self

    app = App()
    transport = Clipboard.member_named(FutureClipboard.declared_name)()
    assert FutureClipboard in Clipboard.members_with(Clipboard)
    assert transport.copy(app, "one declaration café") is transport
    assert app.title == app.clipboard == "one declaration café"
