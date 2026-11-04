"""A comms view's composer sits at the bottom of the conversation and the transcript takes all the height above it."""

from toad.widgets.conversation import Window


async def test_the_composer_sits_at_the_bottom_under_a_full_height_transcript(workspace):
    me = workspace.project.name
    workspace.thread(me, "fixture", running=True)
    comms = workspace.comms
    comms.channels.create_tag("scene")
    for index in range(30):
        comms.messaging.send(me, "#scene", f"scene message {index}")

    async with workspace.app(size=(100, 48)) as ui:
        app, pilot = ui.textual
        await ui.open_channel("#scene", actor=me)
        await ui.until_shows("scene message 29")
        await pilot.pause()
        chat = app.selected_session.query_one("CommsChatView")
        window, composer = chat.query_one(Window), chat.prompt
        stack = composer.parent
        regions = {"chat": chat.region, "window": window.region, "stack": stack.region, "composer": composer.region}
        assert composer.region.bottom == stack.region.bottom == chat.region.bottom, regions
        assert window.region.bottom == stack.region.y, regions
