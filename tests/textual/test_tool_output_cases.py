"""Textual-facing: a newly declared tool output part is composed, painted, collapsed and expanded by ToolCall."""

import asyncio

from acp.schema import ToolCall as AcpToolCall
from toad.line_blocks import Body

from toad.acp.status import ToolCallStatus
from toad.tool_output import SpecificTextToolOutputPart, ToolOutputPart
from toad.widgets.tool_call import ToolCall
from toad.widgets.tool_content import ToolContent


class InspectionToolOutputPart(SpecificTextToolOutputPart):
    @classmethod
    def accepts(cls, text, read_path):
        return read_path is None and text.startswith("DECLARED_NEW_OUTPUT")

    @property
    def line_blocks(self):
        return (Body("case owns: " + self.text),)


def new_case_call() -> ToolCall:
    call = AcpToolCall.model_validate({
        "toolCallId": "new-case", "title": "New case", "status": "completed",
        "content": [{"type": "content", "content": {"type": "text", "text": "DECLARED_NEW_OUTPUT"}}]})
    return ToolCall(ToolCallStatus.from_acp(call))


async def test_a_declared_part_is_adopted_and_painted_without_catalog_edits(workspace):
    async with workspace.app(size=(100, 35)) as ui:
        tool = new_case_call()
        tool.set_expanded(True)
        await ui.conversation.post(tool)
        await ui.until(lambda: tool.query_one(ToolContent).blocks, why="the declared part's content")
        assert InspectionToolOutputPart in ToolOutputPart.members_with(SpecificTextToolOutputPart)
        assert type(tool.output.parts[0]) is InspectionToolOutputPart
        assert tool.query_one(ToolContent).get_clipboard_text() == "case owns: DECLARED_NEW_OUTPUT"
        await ui.until(lambda: tool.query_one(ToolContent)._styled is not None, why="prepared output")
        await ui.until_shows("case owns: DECLARED_NEW_OUTPUT")


async def test_collapsing_removes_the_declared_content_and_expanding_restores_it(workspace):
    async with workspace.app(size=(100, 35)) as ui:
        tool = new_case_call()
        tool.set_expanded(True)
        await ui.conversation.post(tool)
        await ui.until(lambda: tool.query_one(ToolContent).blocks, why="the declared part's content")
        tool.collapse_block()
        await ui.until(lambda: not tool.query_one(ToolContent).blocks, why="the content to be removed on collapse")
        tool.expand_block()
        await ui.until(lambda: tool.query_one(ToolContent).blocks, why="the content to return on expand")
        assert tool.query_one(ToolContent).get_clipboard_text() == "case owns: DECLARED_NEW_OUTPUT"
