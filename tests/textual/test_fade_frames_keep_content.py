"""A fade paints over the lines an entry already rendered: each frame re-paints them, and the
content (Markdown blocks, rows, a new rich Style per segment) is rendered once, not per frame.
The live profile had rich Style construction at 19% of the main thread from exactly this."""

from textual.widget import Widget

from toad.widgets.agent_response import AgentResponse


async def test_an_arrival_fade_renders_its_entry_once(workspace, monkeypatch):
    rendered: list[Widget] = []
    render = Widget._render_content

    def counting(self, paint):
        rendered.append(self)
        return render(self, paint)

    monkeypatch.setattr(Widget, "_render_content", counting)
    async with workspace.app(size=(120, 40)) as ui:
        block = await ui.conversation.post(AgentResponse(""))
        await block.append_fragment("Streamed agent text that fades in as it arrives")
        await ui.step()
        rendered.clear()
        for _ in range(20):
            await ui.pilot.pause(0.025)

    assert sum(isinstance(widget, AgentResponse) for widget in rendered) <= 1
