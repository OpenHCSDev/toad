"""Textual-facing: a large Read tool result prepared by the render workers selects as the exact source text."""

from textual.selection import SELECT_ALL

from support.textual_steps import tool_status
from toad.widgets.tool_call import ToolCall
from toad.widgets.worker_static import WorkerStatic


async def test_read_result_selection_is_the_full_source(workspace):
    source = "# café 界\n" + "def calculate(value: int) -> int:\n    return value + 1\n\n" * 1500
    async with workspace.app(size=(110, 35)) as ui:
        for index in range(2):
            tool = ToolCall(tool_status({
                "toolCallId": f"read-{index}", "kind": "read", "title": "Read example.py",
                "status": "completed", "rawInput": {"path": "example.py"},
                "content": [{"type": "content", "content": {"type": "text", "text": source}}]}))
            await ui.conversation.post(tool)
            tool.set_expanded(True)
            await ui.until(lambda: tool.query(WorkerStatic), seconds=25, why="the read output")
            widget = tool.query_one(WorkerStatic)
            await widget.wait_ready()
            await ui.step()
            actual = widget.get_selection(SELECT_ALL)[0]
            expected = SELECT_ALL.extract(source)
            assert actual == expected, (index, len(actual), len(expected), repr(actual[:90]), repr(actual[-90:]))
