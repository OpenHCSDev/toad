# Physical motion review

The existing `tests/tools/record_installed_tui.py --review-recording` command assumes
a completed capture has `review_intervals`, which are written only on the successful
path. The retained335 capture completed its video but failed its first required
state export, so review raises instead of using its original physical phase markers.

Extend that command in place. Derive intervals from original markers and video
timestamps, produce consecutive frames for actual scroll input, and align the
existing writer and CPU reports. Preserve the raw failure and original hashes.
Review after capture is valid; encoding alone does not claim human inspection or
smoothness. No new recorder, runtime observer, environment or worktree.

## Implemented and verified

22 harness lines deleted. The existing PhysicalJourney owns one marker-based
review interval operation for both capture and retained review. Existing review
encoding now emits consecutive source frames and slowed clips, and retained
review selects the recorded journey, actual recording FPS, original CPU phases
and existing writer timeline. No new recorder, observer or application state.

The actual failed335 video was reviewed through the command: six intervals,
48 consecutive frames each, six correlated CPU phases, empty process cleanup.
All six original raw/report hashes are unchanged. Parent visually inspected
input-held-up and reversal: history is visible, with repeated positions followed
by discrete advances. This is not a smoothness pass. The original application
failure remains false in the review result. Source census parsed47 relevant
tool modules without omissions through the existing refactor-audit parser.

Evidence: physical-motion-review-source.json, physical-motion-review-result.json
and physical-motion-review-original-hashes.json in this directory. No new
application/provider journey was needed: the affected entrypoint is the retained
recording review tool itself, exercised on the original real failed capture.

This supplies U7's frontend motion review in the headless UI plan. State/intents
remain with their existing core owners; each frontend's rendering is checked
from these continuous journeys rather than rebuilding a synthetic backend.
