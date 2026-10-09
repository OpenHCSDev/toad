"""Detached read-only work preserves the native document/reader contract."""
from textual.app import App
from textual.document._document import Selection
from textual.widgets import PreparedTextArea


async def settle(area, pilot):
    await pilot.pause()
    while active := [worker for worker in area.workers
                     if worker.node is area and not worker.is_finished]:
        for worker in active:
            await worker.wait()
        await pilot.pause()


async def test_prepared_load_keeps_selection_and_source_reader_on_resize():
    app = App()
    async with app.run_test(size=(75, 18)) as pilot:
        area = PreparedTextArea(show_line_numbers=True)
        await app.mount(area)
        text = "\n".join(f"line {i}\t" + "long plain [text] λ " * 15 for i in range(160))
        await area.load_text_prepared(text).wait()
        await settle(area, pilot)
        assert area.text == text
        document = area.document
        area.selection = Selection((80, 2), (81, 10))
        selected = area.selected_text
        offset = area.wrapped_document.location_to_offset((60, 0))
        area.scroll_to(y=offset.y, animate=False, immediate=True)
        await pilot.pause()
        reader = area.wrapped_document.offset_to_location(area.scroll_offset)
        wrapped = area.wrapped_document
        await area.load_text_prepared(text).wait()
        assert area.document is document and area.wrapped_document is wrapped
        navigator = area.navigator
        for _ in range(3):
            area._rewrap_and_refresh_virtual_size()
            await settle(area, pilot)
            assert area.wrapped_document is wrapped
            assert area.navigator is navigator
        assert (wrapped._width, wrapped._tab_width) == (area.wrap_width, area.indent_width)
        await pilot.resize_terminal(44, 18)
        await settle(area, pilot)
        assert area.document is document and area.selected_text == selected
        assert area.wrapped_document.offset_to_location(area.scroll_offset)[0] == reader[0]
        resized = area.wrapped_document
        assert resized is not wrapped
        assert (resized._width, resized._tab_width) == (area.wrap_width, area.indent_width)
        area.indent_width = 8
        await settle(area, pilot)
        assert area.wrapped_document is not resized
        assert area.wrapped_document.document is document
        assert (area.wrapped_document._width, area.wrapped_document._tab_width) == (area.wrap_width, 8)


async def test_new_prepared_source_replaces_only_its_original_native_load():
    app = App()
    async with app.run_test() as pilot:
        area = PreparedTextArea()
        await app.mount(area)
        area.load_text_prepared("retired source\n" * 2000)
        await area.load_text_prepared("current source\n" * 300).wait()
        await settle(area, pilot)
        assert area.text == "current source\n" * 300
        assert area.selection == Selection((0, 0), (0, 0))
        original = area.document
        area.load_text_prepared("replaced source\n" * 2000)
        await area.load_text_prepared(area.text).wait()
        await settle(area, pilot)
        assert area.document is original
