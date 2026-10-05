# Body measurement and publication ownership

Base actual merged457 e32253a5601400234b7ef0b5a191185c7427647a. Same finished isolated checkout, successor branch. Only production file: src/toad/widgets/viewport_body.py. Einstein458 renderer/representation/transport and Kepler native owners are unchanged.

## Concrete repeated work

Native Widget._get_box_model acquires its _layout_updates revision before invoking content measurement and stores the result under that revision. The original MeasuredViewportBody.get_content_height recorded derived LiveBody/Materializing(previous LiveBody) width and rows via _update_body_measurement, which invoked _invalidate_layout. That retires this same measurement and its auto-size ancestors inside their getter, although authored content, style, native NodeList and body participation did not change. The next box lookup discards that just-computed revision.

Original body publication start also called refresh(layout=True) after _update had already invalidated layout; Materializing.publication_finished performed another such refresh before _update; captured retirement added another after native child removal, whose original completion owns parent refresh. These consumers recombined a resource transition with separate source/frame publication.

## Existing owner repair

The original body getter records its native-derived extent in the same immutable body resource, retaining its identity guard so a genuine width invalidation cannot be overwritten. It does not manufacture another source retirement or viewport preparation request. Native committed window size changes still own viewport demand. Only LiveBody.measured and Materializing.measured can produce this derived record; unchanged Measured/Rendered measurements retain themselves.

Actual resource/source/participation transitions retain _update_body_measurement as owner. That owner now calls original native refresh(layout=True) once: synchronous subtree/measurement invalidation first, then original pending layout, paint and idle. Delete the three caller refreshes. RenderedBody.height width mismatch and style/capture loss still invalidate through that genuine transition. No native flags, generic batching, capture/membership, worker joins or source admission are bypassed. No new class/cache/flag/wrapper. One production file4+/7-.

## Evidence and remaining qualification

OWNER-BEFORE.json borrows existing refactor-audit Package: full288 Toad/397 tests/41 tools/324 Core/249 Text, zero parse omissions,127 relevant declaration/read/write/call sites. Patterns IMPL-12 and IDEN-1; source contract reviewed directly with native owner.

Working source checkpoint only. Final affected control will extend the existing prepared_height_contract_pilot real mounted App: observe genuine cold native getters without injected state, retained measurement/arrangement reuse, native width/style/relative-height changes, pending writer coverage and original whole shutdown. No current installed/package/native/App authority. No claim of CPU dominance, frame cadence, latency or complete continuous workflow. Existing accepted457 Apps are not repeated.
