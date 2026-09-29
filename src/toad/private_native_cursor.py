"""Bounded, read-only native-history provenance. Never input disposition.

Only validated scope/status/revision and a payload digest survive parsing; raw
proof identifiers/content are not passed to the presentation layer.
"""

from __future__ import annotations

from typing import Literal

CursorStatus = Literal["proven", "coverage_only", "none", "unavailable"]
LABELS = {
    "proven": "Bus history: prior messages included in model input",
    "coverage_only": "Bus history: checked; no model input yet",
    "none": "Bus history: no verified input for this session yet",
    "unavailable": "Bus input verification unavailable — check the ACP log; saved history is separate",
}
TOOLTIP = (
    "Last successful check of bus history for this agent session. A verified input "
    "can be a short relevance check, not a full reply. This does not confirm "
    "receipt or completion of your latest message. Saved transcript availability "
    "is reported separately. If verification is unavailable, check the ACP log; "
    "do not resend input solely because proof is missing."
)
