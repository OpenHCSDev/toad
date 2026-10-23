"""Textual-facing: the welcome title's effect is on the animation clock only while the view shows in a focused terminal, and the view's lists observe the sidebar model only then."""

from toad.screens.welcome import WelcomeEntries, WelcomeTitle


async def test_title_effect_and_list_observation_stop_while_the_view_is_hidden(workspace):
    async with workspace.app(session=False) as ui:
        app, _ = ui.textual
        title, entries = app.screen.query_one(WelcomeTitle), app.screen.query_one(WelcomeEntries)
        clock, access = app.colours.clock, app.coordination_access
        await ui.until(lambda: title.played in title.effects, why="the title's effect to start")
        animation = title.effects[title.played]
        assert clock.running.get(animation) is title and animation.effect is title.played
        assert entries in access.sidebar_views

        session = await ui.new_session()
        assert title.played not in title.effects and title not in clock.running.values()
        assert entries not in access.sidebar_views
        # The built frames stay; the hidden title shows the last one without a timer.
        assert title.render() == app.colours.paint_text(title.played.final, None)

        built = title.played
        await ui.close_tab(session)
        await ui.until(lambda: title.played in title.effects, why="the title's effect to play again")
        assert title.played is built, "the frames were built again for the same colour scheme"
        assert entries in access.sidebar_views

        app.app_focus = False
        await ui.step()
        assert title.played not in title.effects and title not in clock.running.values()


async def test_finished_title_effect_leaves_the_clock(workspace):
    async with workspace.app(session=False) as ui:
        app, _ = ui.textual
        title = app.screen.query_one(WelcomeTitle)
        await ui.until(lambda: title.played in title.effects, why="the title's effect to start")
        await ui.until(lambda: title not in app.colours.clock.running.values(), why="the effect to finish")
        assert title.render() == app.colours.paint_text(title.played.final, None)
