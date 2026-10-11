"""Textual-facing: the history window's preparation demand follows real key travel and revokes the outgoing direction.

Not carried over from the old script: holding a body restoration at its await point (per-message bodies
no longer exist); the revocation is asked of the window's demand directly.
"""

from toad.widgets.agent_response import AgentResponse


async def test_page_up_after_forward_travel_makes_the_forward_demand_stale(workspace):
    async with workspace.app(size=(100, 35)) as ui:
        view = ui.conversation
        window = view.window
        await view.contents.mount(*(AgentResponse(f"## Body {i}\n\n" + "\n\n".join(
            f"Paragraph {j} of body {i}." for j in range(8))) for i in range(12)))
        await ui.until(lambda: window.max_scroll_y > 100, why="a long window")
        window.release_anchor()
        window.focus(scroll_visible=False)
        window.scroll_to(y=window.max_scroll_y / 2, animate=False, immediate=True)
        await ui.step()
        window.scroll_relative(y=1, animate=False, immediate=True)
        await ui.step()
        outgoing = window.lookahead.demand
        assert outgoing.rows(1) > 0, "Initial travel was not forward"
        assert window.lookahead.accepts(outgoing)
        await ui.press("pageup")
        await ui.until(lambda: window.lookahead.demand.rows(1) < 0, why="PageUp to reverse the demand")
        assert window.lookahead.demand is not outgoing
        assert not window.lookahead.accepts(outgoing), "Reversal kept the outgoing preparation batch"
