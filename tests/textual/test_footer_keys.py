"""Textual-facing: the footer keeps its key widgets when only focus notifies, and rebuilds when the displayed bindings change."""

from textual.widgets import Footer
from textual.widgets._footer import FooterKey


async def test_footer_reuses_keys_for_focus_and_rebuilds_for_changed_bindings(workspace):
    async with workspace.app(size=(120, 40)) as ui:
        app, _ = ui.textual
        footer = app.screen.query_one(Footer)
        keys = tuple(footer.query(FooterKey))
        assert keys
        app.screen.refresh_bindings()
        await ui.step()
        assert tuple(footer.query(FooterKey)) == keys
        app.app_focus = False
        await ui.step()
        app.app_focus = True
        await ui.step()
        assert tuple(footer.query(FooterKey)) == keys, "Window focus recreated unchanged footer keys"
        footer.show_command_palette = False
        app.screen.refresh_bindings()
        await ui.step()
        assert not footer.query(".-command-palette")
        footer.show_command_palette = True
        app.screen.refresh_bindings()
        await ui.step()
        assert footer.query(".-command-palette")

        # A requested rebuild can run after focus is lost. Its memo must
        # describe the composed bindings, not the earlier request.
        footer.show_command_palette = False
        with footer._context():
            footer.bindings_changed(app.screen)
        app.app_focus = False
        await ui.step()
        app.app_focus = True
        await ui.step()
        assert not footer.query(".-command-palette")

        def displayed_keys():
            return tuple((key.key, key.key_display, key.description, key.action,
                          key._disabled, key.tooltip) for key in footer.query(FooterKey))

        retained = displayed_keys()
        with footer._context():
            await footer.recompose()
        await ui.step()
        assert displayed_keys() == retained, "Focus restored stale footer bindings"

        # Changed bindings while blurred must still appear on refocus.
        app.app_focus = False
        await ui.step()
        footer.show_command_palette = True
        app.screen.refresh_bindings()
        await ui.step()
        app.app_focus = True
        await ui.step()
        assert footer.query(".-command-palette")
