# Regressions-first handoff to Einstein and Kepler

Implementation checkpoint: `89375d926e3561b3963bfe0009d9d1fd277f5dfd`.
Canonical scope: parent REGRESSIONS-FIRST.md, published owner correction
`da8548a6`; this receipt does not replace the PR275/277 full scope.

## Actual discriminator and limits

Current busy-default capture02 completed in 45.393s. With history focused,
92 PageUp actions produced 478 absolute non-restoration scroll rows and
exactly 478 absolute rows observed by DirectionalPreparation (35 nonzero
observations). Near-zero travel from #254 was not confirmed. Heisenberg holds
the geometry/relocation patch pending compatible installed pre254 `8ea96a37`
control. This is not a pre254 comparison or scrolling acceptance.

With PromptTextArea focused, 91 editor PageUp actions produced zero chat
movement and zero observed travel. These are absent input-to-chat routing,
not evidence that geometry swallowed chat travel. Canonical route is already
in PR275 at `888d7cb8`: PromptTextArea priority PageUp/PageDown bindings delegate
to its original ancestor Conversation.window; ChannelTextArea inherits the
same bindings. The original editor retains focus/document/caret/draft/Undo.
Source-native verification passed; affected installed validation is pending.
No SCOPED_PASS or live/smooth-scroll claim applies to this new route.

Raw correlated recording/profile/native events:
`/home/ts/.cache/agent-scratch/perf275-default-travel-regression-20261001-02`.
Published assessment:
`evidence/foreground-layout-resource-after-271/regression254-current-default-discriminator02.json`.
UI CPU: 85.45% during history-held PageUp, 39.02% mid-history idle. Original
owner PID/birth unchanged; cleanup empty. Native trace overhead 381.35ms,
764 profile samples, zero reported sampling errors; alignment uncertainty
about 64.91ms plus scheduler/sampling limits. No frozen-frame absence claim.

## Exact disjoint grants

- Einstein regression2: MeasuredViewportBody.retained_widget_count,
  materialized_widget_count, retire_measurement, get_content_height, and its
  original measurement/count initialization plus child-custody invalidation
  contract. Instrument the original subtree-count calls before editing. Keep
  the original body measurement owner; no second cost catalog. Coordinate any
  cross-file child mutation producers with their owners before editing.
- Kepler regression3: TranscriptHistory._resource_fragment_budget and the
  DocumentViewport.admission contract, plus the existing _reconcile admission
  result's pass-scoped ownership/consumption only. Instrument calls per actual
  page load before editing. Coordinate count consumption with Einstein. No
  edits to request, _restore_body, compensation or keyboard bindings.
- Heisenberg retains WindowRestoration.geometry,
  DirectionalPreparation.relocated, WorkspaceScreen._refresh_layout,
  DocumentViewport.request/_restore_body, and canonical prompt paging.

Regressions2/3 proceed independently after their own discriminators. #254
patch remains held; broader A-E waits. No peer messaging tool is exposed in
this session, so this published handoff requires parent relay to the two
existing contexts. Do not delay urgent parent485/487/488/278 paired release279
for this performance control or route validation. The normal immutable
builder remains Mendel; no duplicate builder or capture is launched here.

## Fresh route/control boundary and one next installed gate

Re-reading the raw capture02 clock interval confirms 91 editor PageUp actions
and **zero original Window PageUp actions**, not merely zero resulting travel.
Chat-focused interval has 92 original Window PageUp actions and478 observed
rows. This distinguishes absent focus routing from compensation.

The existing recorder now declares `input_paging_acceptance`: held input-focused
PageUp **and PageDown**, original editor/caret/draft/window retention, continued
history-focused held scroll, mid-history15s idle and separateEnd. Its checks
require both original Window action delivery during each focused input interval
and native reader/source movement. Background source progress alone cannot
satisfy the gate. Video/profile review remains required; native assertions
never supply smooth-scroll/zero-frozen-frame acceptance.

Builder dependency: the current immutable277 prefix iscf7 and lacks888d's
canonical route. Mendel needs ONE normal immutable restage of current275 head,
paired with the declared current receiving Core/Text/native cohort after279;
no guessing old public source decoders. Include production route888d and the
latest recorder/monitor; invoke existing_thread / input_paging_acceptance with
--capture-state --scroll-travel --profile on a busy original approved source,
isolatedst/Xvfb. Busy-channel entry/coverage must be included through the real
channel-bar owner before claiming channel acceptance; no quiet/provider-only
replacement. Do not change/freeze/retest urgent279 on this dependency.

Einstein regression2 and Kepler regression3 retain the disjoint grants above.
#254 production geometry remains unchanged pending the compatible8ea96a37
installed control. No speculative geometry edit or second builder/capture.
