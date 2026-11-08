"""Review control: layout discovery must not change a published read answer."""

from toad.widgets.comms_chat import CommsChatView


async def test_unpublished_width_measure_keeps_published_message_visibility(workspace):
    workspace.thread("peer", "team", running=True)
    for index in range(20):
        workspace.comms.messaging.send(
            "peer", "#team", f"message {index:02} " + (f"body{index:02} " * 45))
    async with workspace.app(size=(120, 41)) as ui:
        await ui.open_channel("#team", actor=workspace.viewer)
        await ui.until_shows("body19")
        app = ui.textual[0]
        history = app.screen.query_one(CommsChatView).message_history
        await history._read_worker.wait()
        before = {part.message.view_key for part in history.read_fragments()}
        compositor = app.screen._compositor
        published = compositor.published_widgets
        page = next(page for page in history.pages
                    if page.parent is history and page in published)
        old_width = page.line_width
        with app.screen.hold_frames():
            page.styles.width = 40
            _ = compositor.full_map
            assert page.line_width != old_width, "control must actually remeasure the body"
            assert compositor.published_widgets == published
            after = {part.message.view_key for part in history.read_fragments()}
            assert after == before, (before, after, old_width, page.line_width)
