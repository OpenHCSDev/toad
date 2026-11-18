"""A sent message is on screen at every frame from Send until the history draws it: in the
delivery preview above the prompt, then in the history. Tristan, 2026-11-18: "the queue shows
up and then the message gets submitted and the queue disappears, but then there's a gap where
I don't see the queue and I don't see the message on the screen"."""

from types import MethodType

from toad.prompt_actions import SubmitAction


def region_text(lines: list[str], region) -> str:
    return "\n".join(line[region.x:region.right] for line in lines[region.y:region.bottom])


async def test_every_frame_shows_a_sent_message_in_the_preview_or_the_history(workspace):
    from toad.widgets.comms_chat import CommsChatView
    from toad.widgets.conversation import Window
    from toad.widgets.prompt import QueueSummary

    workspace.thread("peer")
    async with workspace.app(size=(110, 32)) as ui:
        await ui.open_direct("peer", actor=workspace.viewer)
        chat = ui.app.selected_session.query_one(CommsChatView)
        window, summary = chat.query_one(Window), chat.query_one(QueueSummary)
        editor = chat.prompt.prompt_text_area
        app, _pilot = ui.textual
        sent: list[str] = []
        frames: dict[str, list[tuple[bool, bool]]] = {}
        shown = type(app)._display

        def display(self, screen, renderable) -> None:
            shown(self, screen, renderable)
            lines = ui.visible_lines()
            history = region_text(lines, window.region)
            preview = region_text(lines, summary.region) if summary.display else ""
            for marker in sent:
                track = frames.setdefault(marker, [])
                if not (track and track[-1][1]):
                    track.append((marker in preview, marker in history))

        app._display = MethodType(display, app)
        try:
            for index in range(10):
                marker = f"NEVER_VANISHES_{index}"
                await ui.write_draft(marker)
                sent.append(marker)
                editor.schedule_submission(SubmitAction())
                await ui.until(lambda: frames.get(marker) and frames[marker][-1][1],
                               why=f"{marker} drawn in the history")
        finally:
            del app._display
        gaps = {marker: sum(1 for preview, history in track if not (preview or history))
                for marker, track in frames.items()}
        assert not any(gaps.values()), f"frames showing a sent message nowhere: {gaps}"
        await ui.until(lambda: not chat.submissions.previewed, why="every drawn message retired from the preview")


async def test_a_sent_message_scrolled_past_by_a_long_reply_leaves_the_preview(workspace):
    """Shown means the history drew it, above the window's bottom edge: a long reply landing in
    the same read pushes it off the top, and it still leaves the preview."""
    from unittest.mock import patch

    from toad.client.bus_submission import BusSubmissionExecution
    from toad.core.input_events import UserInputSubmitted
    from toad.widgets.comms_chat import CommsChatView

    comms = workspace.comms
    workspace.thread("peer")
    commit = BusSubmissionExecution.commit

    async def commit_then_reply(execution, *args, **kwargs):
        sent = await commit(execution, *args, **kwargs)
        comms.messaging.send("peer", workspace.viewer, "\n\n".join(f"reply line {n}" for n in range(80)))
        return sent

    async with workspace.app(size=(110, 24)) as ui:
        await ui.open_direct("peer", actor=workspace.viewer)
        chat = ui.app.selected_session.query_one(CommsChatView)
        with patch.object(BusSubmissionExecution, "commit", commit_then_reply):
            await chat.submissions.received(UserInputSubmitted("SCROLLED_PAST_PREVIEW"))()
            await ui.until(lambda: ui.shows("reply line 79") and not chat.submissions.previewed,
                           why="the long reply drawn and the sent message gone from the preview")
