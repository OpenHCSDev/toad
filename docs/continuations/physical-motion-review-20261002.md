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
