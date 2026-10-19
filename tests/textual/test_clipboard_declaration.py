"""Textual-facing: a clipboard transport declared in one place is chosen by name and publishes through its own publish."""

from textual.app import App

from toad.clipboard import Clipboard


def test_new_clipboard_case_is_declared_and_chosen_by_name():
    class FutureClipboard(Clipboard):
        def publish(self, app, text):
            app.title = text
            return self

    app = App()
    transport = Clipboard.member_named(FutureClipboard.declared_name)()
    assert FutureClipboard in Clipboard.members_with(Clipboard)
    assert transport.publish(app, "one declaration café") is transport
    assert app.title == "one declaration café"
