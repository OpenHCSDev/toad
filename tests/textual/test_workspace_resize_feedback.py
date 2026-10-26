"""A layout receipt cannot overwrite a later terminal viewport request."""
from textual.events import Resize
from textual.geometry import Size


async def test_latest_terminal_resize_survives_workspace_layout_output(workspace):
    async with workspace.app(size=(155, 18)) as ui:
        app = ui.app
        requests = []
        screen = app.workspace_screen
        resize = screen._screen_resized
        def record(size):
            requests.append((size, screen.outer_size, screen.virtual_size))
            assert len(requests) <= 2, f'Layout output fed back as a viewport request: {requests}'
            resize(size)
        screen._screen_resized = record
        # App receives both terminal sizes before its screen processes them.
        # An ordinary queued callback separates the original requests.
        await app._on_resize(Resize(Size(155, 40), Size(155, 40)))
        app._check_resize()
        app.screen.call_later(lambda: None)
        await app._on_resize(Resize(Size(155, 18), Size(155, 18)))
        app._check_resize()
        await ui.step()
        assert app.workspace_screen.outer_size == app.size == Size(155, 18)
        await ui.type('still responsive')
        assert ui.conversation.prompt.text == 'still responsive'
