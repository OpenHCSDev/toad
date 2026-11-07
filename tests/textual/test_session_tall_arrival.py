"""Where a following reader lands when a tall message arrives in the session conversation.

Tristan, three times: a large message "comes in in one shot and it scrolls to the bottom of
the message, and then the fade effect happens, but the scrolling doesn't actually match it".
A tall arrival into a channel behaves (test_tall_arrival_scroll), and so does a tall saved
row here, which placed its head rather than parking the reader below it. Both saved-row
paths were ruled out by measurement, which left the live block: it ran one fade over its
whole body while only the pager reported rows still to rise, so a streaming answer appeared
at once with the tail already at its bottom. A live block now runs the same cascade and
reports its own unrisen rows, and the window asks both kinds of holder.
"""

import os
from dataclasses import replace

from agent_comms.child_process import ProcessIdentity
from agent_comms.fresh_private_session import create_fresh_private_session
from agent_comms.session_file import RegistrySessionLocation

from support.agents import deliver
from support.coordination import carrying, coordination_fact
from toad.frame_presentation import ARRIVAL
from toad.widgets.agent_response import AgentResponse
from toad.widgets.transcript_history import TranscriptHistory


async def session_following_its_tail(workspace, ui, backlog: int):
    """The session conversation, bound to its thread, scrolled to the end of a peer backlog."""
    comms = workspace.comms
    saved = create_fresh_private_session(workspace.project / "sessions",
                                         worktree=workspace.project).path
    thread = comms.registry.declare(replace(
        workspace.thread("source"),
        session_file=RegistrySessionLocation.from_path(str(saved), comms.root)))
    workspace.thread("peer")
    for index in range(backlog):
        comms.messaging.send("peer", "source", f"BACKLOG {index:02d}: " + "body text " * 8)

    view = ui.conversation
    agent = ui.detached_agent("session-tall-arrival")
    view.bind_agent(agent)
    coordination = replace(
        coordination_fact(comms, thread.name, owner=ProcessIdentity.capture(os.getpid()),
                          worktree=workspace.project, model="test-model"),
        thread=thread.incarnation)
    await deliver(agent, carrying(coordination))
    # The view opens at the tail, so the newest backlog row is the one on screen.
    await ui.until(lambda: f"BACKLOG {backlog - 1:02d}" in ui.painted(view.window),
                   why="the peer backlog")
    history = view.contents.query_one(TranscriptHistory)
    return view, history, view.window, agent


async def test_a_tall_arrival_does_not_land_the_session_reader_at_its_bottom(workspace):
    comms = workspace.comms
    async with workspace.app(size=(120, 35)) as ui:
        view, history, window, agent = await session_following_its_tail(workspace, ui, backlog=30)
        await ui.until(lambda: window.follows_tail, why="the reader on the tail")
        viewport = window.scrollable_content_region.height

        before = window.max_scroll_y
        comms.messaging.send("peer", "source", "TALL ARRIVAL\n" + "\n".join(
            f"row {row} of a message taller than the window" for row in range(viewport + 12)))
        await ui.until(lambda: "TALL ARRIVAL" in ui.painted(window), why="the tall arrival")

        # The premise, measured rather than assumed: markdown joins single newlines, so a
        # message built from them can wrap into one paragraph far shorter than intended.
        assert window.max_scroll_y - before > viewport, (
            f"the arrival was not taller than the window: max_scroll_y {before} -> "
            f"{window.max_scroll_y} against a viewport of {viewport}")
        assert window.scroll_y < window.max_scroll_y, (
            f"parked at the bottom of a message taller than the window: "
            f"scroll_y={window.scroll_y} max_scroll_y={window.max_scroll_y} viewport={viewport} "
            f"tail_scroll_y={window.tail_scroll_y} unrevealed={history.unrevealed_rows()} "
            f"phase={type(history.effect_phase(ARRIVAL)).__name__} "
            f"reader={type(window.reader_position).__name__}")


async def test_the_tail_never_sits_at_the_bottom_while_rows_are_still_rising(workspace):
    """Where the reader is *during* the arrival, not after it settles.

    The earlier assertion read the end state, which is the head placed correctly, and so
    could not see Tristan's report: "it scrolls to the bottom of the message, and then the
    fade effect happens". This records every frame the terminal received across the arrival.
    """
    comms = workspace.comms
    async with workspace.app(size=(120, 35)) as ui:
        view, history, window, agent = await session_following_its_tail(workspace, ui, backlog=30)
        await ui.until(lambda: window.follows_tail, why="the reader on the tail")
        viewport = window.scrollable_content_region.height

        screen = ui.app.screen
        published = screen._on_frame_published
        frames: list[tuple[float, float, int]] = []

        def recording() -> None:
            published()
            frames.append((window.scroll_y, window.max_scroll_y, history.unrevealed_rows()))

        screen._on_frame_published = recording
        try:
            comms.messaging.send("peer", "source", "TALL ARRIVAL\n" + "\n".join(
                f"row {row} of a message taller than the window" for row in range(viewport + 12)))
            await ui.until(lambda: "TALL ARRIVAL" in ui.painted(window), why="the tall arrival")
            for _ in range(6):
                await ui.step()
        finally:
            screen._on_frame_published = published

        # Vacuous otherwise: a filter on held > 0 that never matches proves nothing.
        assert any(held > 0 for _scroll, _bottom, held in frames), (
            f"no frame held a row back, so this arrival never revealed progressively; "
            f"frames={frames[:12]}")
        parked = [(scroll, bottom, held) for scroll, bottom, held in frames
                  if held > 0 and scroll >= bottom]
        assert not parked, (
            f"the tail sat at the bottom while {parked[0][2]} rows had not risen; "
            f"frames={frames[-8:]}")


async def test_a_tall_live_answer_holds_its_own_rows_back(workspace):
    """The path Tristan actually saw: the agent's own streamed answer, not a peer's saved row.

    A live block is not one of the window's pagers, so while it ran a single body-wide fade
    nothing reported rows still to rise and `tail_scroll_y` was the very bottom: the answer
    appeared whole, the tail sat under it, and the fade then played where the reader had
    already arrived.
    """
    async with workspace.app(size=(120, 35)) as ui:
        view = ui.conversation
        window = view.window
        window.anchor()
        viewport = window.scrollable_content_region.height
        before = window.max_scroll_y

        def held() -> int:
            return sum(holder.unrevealed_rows() for holder in window.row_holders)

        screen = ui.app.screen
        published = screen._on_frame_published
        frames: list[tuple[float, float, int]] = []

        def recording() -> None:
            published()
            frames.append((window.scroll_y, window.max_scroll_y, held()))

        screen._on_frame_published = recording
        try:
            live = await view.post(AgentResponse(""))
            await live.append_fragment("LIVE TALL ANSWER\n\n" + "\n\n".join(
                f"row {row} of a live answer taller than the window"
                for row in range(viewport + 12)))
            # The cascade runs for ARRIVAL.duration, so the frames are read as it plays and
            # not after: measuring once at the end reads a reveal that has already finished.
            await ui.until(lambda: window.max_scroll_y > before + viewport,
                           why="the live answer laid out taller than the window")
            for _ in range(4):
                await ui.step()
        finally:
            screen._on_frame_published = published

        # The premise, measured: blank lines keep the rows separate paragraphs, so the answer
        # really is taller than the window rather than one wrapped paragraph.
        assert window.max_scroll_y - before > viewport, (
            f"the live answer was not taller than the window: max_scroll_y {before} -> "
            f"{window.max_scroll_y} against a viewport of {viewport}")
        # The window asks the block, which is not one of its pagers: the sum that counted
        # saved pages only is why a live arrival's tail went straight to the bottom.
        assert live in list(window.row_holders), (
            f"a mounted live block is not one of the window's row holders: "
            f"{[type(holder).__name__ for holder in window.row_holders]}")
        # Vacuous otherwise: with nothing held back every frame trivially sits below the end.
        assert any(rows > 0 for _scroll, _bottom, rows in frames), (
            f"no frame held a row back, so the live answer never revealed progressively; "
            f"runs={tuple(live.cascade_runs())} frames={frames[:12]}")
        waited = [(scroll, bottom, rows) for scroll, bottom, rows in frames
                  if rows > 0 and scroll < bottom]
        assert waited, (
            f"the tail never waited above the rows still rising, so the answer appeared whole "
            f"with the reader already at its end; frames={frames}")
        # And it does reach the end once they have all risen.
        assert frames[-1][0] >= frames[-1][1] and frames[-1][2] == 0, (
            f"the reveal left the reader short of the end: {frames[-1]}")
