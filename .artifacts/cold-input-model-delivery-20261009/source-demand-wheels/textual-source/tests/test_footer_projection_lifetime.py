import asyncio
from unittest.mock import patch

import pytest

from textual.app import App
from textual.binding import Binding
from textual.widget import Widget
from textual.widgets import Footer, Input
from textual.widgets._footer import FooterKey, KeyGroup


async def test_repeated_unchanged_binding_notifications_keep_native_key_owners():
    class FooterApp(App):
        BINDINGS = [Binding("f2", "test", "Test")]

        def compose(self):
            yield Input()
            yield Footer()

        def action_test(self):
            pass

    app = FooterApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        footer = app.query_one(Footer)
        await footer._reconcile_bindings()
        await pilot.pause()
        keys = tuple(footer.query(FooterKey))
        assert keys
        original_key = next(key for key in keys if key.key == "f2")
        with patch.object(footer, "recompose", wraps=footer.recompose) as recompose:
            for _ in range(50):
                app.screen.refresh_bindings()
            await pilot.pause()
            assert not recompose.called
            assert tuple(footer.query(FooterKey)) == keys
        app.bind("f3", "another_test", description="Changed action")
        app.screen.refresh_bindings()
        await pilot.pause()
        assert any(key.key == "f3" for key in footer.query(FooterKey))
        assert next(key for key in footer.query(FooterKey) if key.key == "f2") is original_key
        with patch.object(app, "get_key_display", return_value="Updated display"):
            app.screen.refresh_bindings()
            await pilot.pause()
            assert original_key.key_display == "Updated display"
            assert original_key.key == "f2" and original_key.action == "test"
            assert next(key for key in footer.query(FooterKey) if key.key == "f2") is original_key


async def test_keymap_and_binding_owner_stay_authoritative():
    actions = []

    class Owner(Widget, can_focus=True):
        BINDINGS = [Binding("f2", "test", "Test", id="test")]

        def action_test(self):
            actions.append(self.id)

    class OwnerApp(App):
        def compose(self):
            yield Owner(id="first")
            yield Owner(id="second")
            yield Footer()

    app = OwnerApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        footer = app.query_one(Footer)
        key = next(key for key in footer.query(FooterKey) if key.action == "test")
        key.on_mouse_down()
        await pilot.pause()
        app.query_one("#second").focus()
        await pilot.pause()
        assert next(key for key in footer.query(FooterKey) if key.action == "test") is key
        key.on_mouse_down()
        await pilot.pause()
        app.set_keymap({"test": "f3"})
        await pilot.pause()
        assert key.key == "f3"
        assert key.key_display == app.get_key_display(app.screen.active_bindings["f3"].binding)
        key.on_mouse_down()
        await pilot.pause()
        assert actions == ["first", "second", "second"]


@pytest.mark.parametrize("mixed", [False, True])
async def test_group_transitions_match_fresh_native_composition(mixed):
    group = Binding.Group("Grouped actions", compact=True)

    class GroupApp(App):
        BINDINGS = [
            Binding("f2", "first", "First", group=group, tooltip="First help"),
            Binding("f3", "second", "Second", group=group),
            Binding("f4", "flat", "Flat", show=mixed),
        ]
        state = True

        def compose(self):
            yield Footer()

        def check_action(self, action, parameters):
            return self.state if action == "second" else True

    def displayed(footer):
        return [
            (key.key, key.key_display, key.description, key._disabled, key.tooltip, key.classes)
            for key in footer.query(FooterKey)
        ]

    app = GroupApp()
    async with app.run_test(size=(120, 24)) as pilot:
        await pilot.pause()
        footer = app.query_one(Footer)
        for state in (None, False, True):
            app.state = state
            footer.compact = state is None
            footer.show_command_palette = state is not False
            app.screen.refresh_bindings()
            await pilot.pause()
            before = displayed(footer)
            groups = len(footer.query(KeyGroup))
            assert groups == (0 if state is False else 1)
            if state is None:
                key = next(key for key in footer.query(FooterKey) if key.key == "f3")
                assert key._disabled and key.has_class("-disabled")
                assert key.tooltip == "Second"
                with patch.object(app, "simulate_key") as dispatch:
                    key.on_mouse_down()
                    dispatch.assert_not_called()
            footer.refresh(recompose=True)
            await pilot.pause()
            assert displayed(footer) == before


@pytest.mark.parametrize("remove_footer", [False, True])
async def test_binding_notification_during_publication_is_not_lost(remove_footer):
    class FooterApp(App):
        BINDINGS = [Binding("f2", "test", "Test", id="test")]

        def compose(self):
            yield Footer()

    app = FooterApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        footer = app.query_one(Footer)
        entered, release = asyncio.Event(), asyncio.Event()
        original = footer._reconcile_keys

        async def gated(*args, **kwargs):
            entered.set()
            await release.wait()
            await original(*args, **kwargs)

        with patch.object(footer, "_reconcile_keys", side_effect=gated):
            app.set_keymap({"test": "f3"})
            try:
                await asyncio.wait_for(entered.wait(), 5)
                if remove_footer:
                    await asyncio.wait_for(footer.remove(), 5)
                else:
                    app.set_keymap({"test": "f4"})
                    footer.bindings_changed(app.screen)
            finally:
                release.set()
            await pilot.pause()
        if remove_footer:
            assert footer._closed
            assert not getattr(footer, "__watchers", {}).get("compact")
        else:
            key = next(key for key in footer.query(FooterKey) if key.action == "test")
            assert key.key == "f4"
            assert "f4" in app.screen.active_bindings
