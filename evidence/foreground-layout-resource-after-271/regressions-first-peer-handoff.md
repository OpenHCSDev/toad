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
