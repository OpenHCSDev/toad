"""A file named in an agent answer is a link to the project file; clicking it opens the file's preview and returning keeps the draft."""

from support.agents import peer

ANSWER_SOURCE = "file.md and `file.md` but `run file.md`; [website](https://example.com)."


def file_links(ui, text):
    """The click actions on each drawn occurrence of `text` that is a link."""
    drawn = sum(text in line for line in ui.visible_lines())
    return [link for occurrence in range(drawn) if (link := ui.link_at(text, occurrence=occurrence)) is not None]


async def test_file_link_in_answer_opens_preview_and_return_keeps_draft(workspace):
    target = workspace.project / "file.md"
    target.write_text("# REAL_MARKDOWN_FILE_PREVIEW\n\n```python\nvalue = 42\n```\n")
    async with workspace.app(size=(110, 36), agent=peer("echo")) as ui:
        await ui.until_agent_ready()
        owner = ui.selected_tab
        await ui.write_draft(ANSWER_SOURCE)
        await ui.press("enter")
        await ui.until_shows("PEER_ANSWER")
        await ui.write_draft("KEEP_MARKDOWN_DRAFT")
        links = file_links(ui, "file.md")
        assert sum(f"toad-file:{target}" in str(link) for link in links) == 2, links
        assert any("https://example.com" in str(link) for link in file_links(ui, "website")), ui.visible_text()
        drawn = [i for i, line in enumerate(line for line in ui.visible_lines() if "file.md" in line)]
        await ui.click("file.md", occurrence=next(i for i in drawn if ui.link_at("file.md", occurrence=i) is not None))
        await ui.until_shows("REAL_MARKDOWN_FILE_PREVIEW")
        assert ui.selected_tab != owner
        await ui.close_tab(ui.selected_tab)
        await ui.until(lambda: ui.selected_tab == owner, why="the conversation tab to be shown again")
        assert ui.draft() == "KEEP_MARKDOWN_DRAFT"
