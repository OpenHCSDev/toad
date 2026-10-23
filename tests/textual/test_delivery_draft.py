"""Actual mounted compose controls preserve the draft across delivery failures."""

import pytest
from agent_comms.acp_extension import (
    BackendDeliveryFailure,
    ClaimBlockedFailure,
)


@pytest.mark.parametrize(
    "failure",
    [
        BackendDeliveryFailure("refused"),
        ClaimBlockedFailure("blocked"),
    ],
)
@pytest.mark.parametrize("draft", ["", "a newer unsent draft"])
async def test_failure_returns_only_its_text_without_overwriting_a_newer_draft(
    workspace, failure, draft
):
    workspace.thread("peer", "team")
    async with workspace.app() as ui:
        await ui.open_channel("#team", actor=workspace.viewer)
        view = ui.conversation
        await ui.write_draft(draft)
        area = view.prompt.prompt_text_area
        document = area.document
        failure.present(view, "the failed message")
        assert view.prompt.text == (draft or "the failed message")
        if draft:
            assert area.document is document
