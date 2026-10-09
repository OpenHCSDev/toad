# Component ancestry identity

Five lines deleted first across product/test diff; product removes the independent all_ids policy from Stylesheet._css_path_key. Both native widget and component style signatures now use the existing declaration-derived _ids_in_rules index. No new cache or registry. IDEN-7: irrelevant source/container IDs cannot change matched component styles. Referenced ancestor IDs remain in the key; classes, types, pseudo state and CSS rule/source changes remain authoritative.

Existing test family extended with mounted native App reparent between same-type containers whose IDs are not referenced: old1738 installed failed component identity despite identical red rules. Installed candidate64stylesheet/reparent tests PASS1.29s, including later declared-ID style, ordinary class changes, CSS edits and focus-within uncacheable behavior. No mocks on added UI path.

Paired Toad continuation uses shipping1684cc1d2bc/core366db7d6183. Actual continuous Pi/ACP saved-state native journey will verify retained complete rendered caches, raw reads0, stronger1.2second idle no-miss/no-replay, physical navigation/channel/participant/fork/reply, editor/reader custody and EXIT0. Not ready until actual affected path receipt.

Fresh168 profile still shows0.65s cumulative reparent/style work over5returns, with about0.33s component-style handling. These are profiler costs, NOT unprofiled switch latency or completed30–40ms target. Parent owns targeted core history projection separately; no projection/stat cache here. No live/route edits. CI/final latency target deferred for useful checkpoints.

Paired actual final native saved-state continuous gate PASS EXIT0 with ToadPR174/corePR374+current main. All13/17/13 visible rendered leaf/cache identities retained, raw0/0/0, 1.2s idle global misses65->65/provider3->3/work[]/pending0, End/reversepaint/forkfirstanswer/channelreply/authorobservation. Distinct stopped-DM return1/1 passes. No final performance target claim; profile is guidance not matched matrix. Evidence Toad174 evidence/workspace-latency/final-continuous.txt. Existing64 stylesheet/reparent tests pass, old1738 actual same ancestry test failed before fix.
