# Synchronous idle admission

Screen previously prepared visible/background roots before its timer decision, then acquired them again for callbacks. Timer.resume only sets an asyncio.Event; callback admission had no internal await and only queues sender-owned callbacks. Neither dispatches another task during this synchronous interval. Damage-only idle admission and its callbacks now borrow one acquired tuple, including a legitimately empty tuple. Nothing is retained across events or publication.

Callback admission is now synchronous. Idle supplies any roots it acquired; the existing timer call_next invocation acquires its own roots. These are the two native callers; no tracked override was found across native, Toad and Core. Arbitrary external dynamic callers remain unresolved by lexical AST. The private method is no longer awaitable; its one awaited native caller was migrated without an async wrapper or alias.

The existing flags derive one _refresh_requested predicate used by idle, _refresh_pending and spatial sender checks. Required work or dirty widgets resume the existing timer without preparing roots merely for that decision. Damage-only work still acquires preparation effects, rechecks flags changed by preparation, and excludes held regions. Held-only damage keeps the timer quiet; required callback and publication preparation still request source work.

Paint is a distinct acquisition: queued source, follow, scroll, layout and screen membership can change after idle returns. _compositor_refresh still acquires its exact roots for damage exclusion, background/inline rendering and _on_frame_published. No readiness cache, frame state, mask, queue, new timer or Toad edit. Preparation effects occur at required sender admission/publication rather than a timer decision whose answer is already known.

AST before:249 native production/467 tests/288 Toad/324 Core modules, zero omissions. After native:249/zero. Existing native callback invocation supports sync and async functions. Twelve production lines replaced.

Seven real framework controls PASS/.79s: held and empty cohorts, required-scroll timer progress without idle-only preparation, fresh paint acquisition, held damage/release, real run_async sender tasks, inline and translucent-background exclusion. One original source sidebar App PASS/empty stderr,508 widgets/10 tabs/no provider. Each profiled toggle makes2 preparations versus3 in the retained prior source App. Frame medians37.0/44.8ms versus38.2/39.1ms have varying tails: no reliable overall speedup or installed/live/physical scrolling claim.

The retained-tool fixture was read, not executed: its private_native_wire requires a native package purpose outside this assignment. No package, SDK, provider, public or borrowed-prefix operation. RESULT.json binds original logs/profiles; accepted prior evidence stays unchanged.
