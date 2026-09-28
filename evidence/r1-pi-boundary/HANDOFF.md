# R1 Pi payload integration in Toad

Core196 is merged. This paired change pins agent-comms to ae0545dfcfb742d65d22b5125bf6436be7016c54 and retains current Textual main. No production Toad caller required an API change: ToolDiff and TranscriptEvent remain its public boundary.

The transcript process pilot now injects the renderer through the current Toad constructor, supplies unique uncached content for each publication race, and preserves the bound session cursor. Its old property monkeypatch observed a different renderer; later retries exposed cache reuse and inconsistent fixture cursors. Failed logs are retained. No production history bypass or weakened assertion was added.

Source and installed-wheel tool_diff_pilot and transcript_process_pilot pass. The latter runs actual process rendering and verifies exact fragments, foreground/Textual heartbeats, stale result suppression, cancellation, scroll intent and detach. Installed sample: 1217 exact fragments, 125 foreground and127 Textual heartbeats, max Textual gap12.2ms. This is a focused headless result, not an X11 latency claim.

Parent core evidence/r1-integration contains bounded latest/prior page acceptance for all88 saved native files, with no inputs sent. Installed real-provider queue/compaction and mounted original-history acceptance are parent-owned and proceed before live activation. Current production remains R5 until that acceptance succeeds. CI deferred.
