"""Textual-facing: a collapsed tool call mounts no output tree, expanding mounts it, and long histories of tool calls and answers stay a small number of widgets."""

from support.textual_steps import tool_status
from toad.setting_choices import NeverExpansion
from toad.widgets.agent_response import AgentResponse
from toad.widgets.tool_call import ToolCall, ToolCallHeader
from toad.widgets.tool_content import ToolContent
from toad.preferences import SETTINGS

TEXT = "\n\n".join(f"## Section {i}\n\nOutput paragraph {i}" for i in range(40))


def read_call(name, text):
    return tool_status({"toolCallId": name, "title": f"Read {name}", "kind": "read", "status": "completed",
                        "content": [{"type": "content", "content": {"type": "text", "text": text}}]})


async def test_collapsed_tool_output_is_not_parsed_and_expands_on_demand(workspace):
    async with workspace.app(size=(120, 40)) as ui:
        app, _ = ui.textual
        app.saved_settings.set(SETTINGS.tools.expand, NeverExpansion)
        tools = [ToolCall(read_call(f"tool-{i}", TEXT)) for i in range(40)]
        await ui.conversation.contents.mount(*tools)
        await ui.step()
        last = tools[-1]
        header = last.query_one(ToolCallHeader)
        for _ in range(5):
            await last.update_tool_call(last.tool_call)
        await ui.step()
        assert all(not tool.query_one(ToolContent).blocks for tool in tools), "Collapsed output was prepared"
        assert sum(len(list(tool.query("*"))) for tool in tools) <= len(tools) * 3
        assert last.query_one(ToolCallHeader) is header
        last.expanded = True
        await ui.until(lambda: last.query_one(ToolContent).blocks, why="the expanded output")
        assert last.query_one(ToolContent).get_clipboard_text() == TEXT
        last.expanded = False
        await ui.until(lambda: not last.query_one(ToolContent).blocks, why="the collapsed output to go")
        await last.update_tool_call(read_call("tool-39", "## Updated\n\nNew result"))
        last.expanded = True
        await ui.until(lambda: last.query_one(ToolContent).blocks and "New result" in last.query_one(ToolContent).get_clipboard_text(),
                       why="the updated output")


async def test_many_long_answers_stay_small_widgets(workspace):
    async with workspace.app(size=(120, 40)) as ui:
        conversation = ui.conversation
        await conversation.contents.remove_children()
        for _ in range(8):
            old = await conversation.post(AgentResponse(TEXT))
            await old.finish_stream()
            await ui.step()
        assert all(len(list(child.query("*"))) < 150 for child in conversation.contents.children)
        assert all(child.body.text == TEXT for child in conversation.contents.children)
