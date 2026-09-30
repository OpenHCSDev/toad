# PR238 UI-only immutable stage — Ready for parent review

Stage: `/home/ts/.local/share/agent-comms/runtime-goal-observation-20260930`.
Toad merged629cca65; Core4295/Text2e49/ACP SDK0.12.1/nativee36 unchanged.
Exact full pins and native path are in the source/staging/ready receipts.

One normal frozen68 installation from accepted `runtime-owner-cli-config`
package freeze, only Toad git requirement changed. uv's normal wheel/cache and
hardlink mechanism used; no source worktree clone, native copy, backend adapter,
new builder or extra helper fleet. All273 installed Toad Python files equal the
exact merged629 Git source. Core/Textual distribution provenance unchanged;
all68 installed requirements equal the frozen recipe and `uv pip check` passed.
Source production delta:5 lines added/5 deleted in two files.

Existing `RuntimeSelection.publish_verified_stage` published immutable metadata
from this same verified staging receipt and its existing runtime preflight passed.
Owned probe processes cleaned, no remaining PIDs/errors. Public root not loaded,
UI not launched, no provider/native inputs, defaults not changed, owners not
restarted. Parent alone reviews/activates this UI-only stage. Backend ABI unchanged.

Affected installed imports passed: declaration owner
`toad.session_observation.GoalObservation` and
`ConversationSessionBinding.refresh_native_projection` (now synchronous,
invalidation goes through the existing original goal observer). The initial probe
incorrectly imported GoalObservation from transcript_publication; preserve the
ImportError in affected-import-proof.json. This was probe setup, after metadata
preflight passed, not an installed product failure. Corrected only the import;
no rebuild or repeated preflight/UI/provider gate.

Sch238 matcheddef49 original held-read A/B/A firstpaint/ACP journey and four
required guards were already accepted. His post-merge9ba receipt commit has no
production/dependency delta and does not require another build. New273 source
comparison closes provenance to merged629; no repeated full journey here.
Actual mid-active compaction attribution remains open with its named owner.

The preceding57.664s actual default controls receipt258e remains intact:
UI controls scopedPASS, fresh NRA stopped_drain/NativePiUnavailable/UNKNOWN
separate and **overallReadyfalse**. This stage preparation does not fix or hide
that backend admission failure. Parent/Arendt continue that scope independently.
