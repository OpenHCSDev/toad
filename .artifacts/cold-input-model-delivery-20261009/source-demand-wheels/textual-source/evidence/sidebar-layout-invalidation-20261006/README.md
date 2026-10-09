# Skip held-subtree traversal when none is held

The sidebar profile exposed complete committed-map ancestry scans in
`Compositor._arrange_root` and `deferred_regions` even with no held roots.
Screen also scanned callback ancestry and retained layout members against an
empty root set. The existing owners now derive the empty result immediately.
Nonempty roots use the original matching, damage and callback rules. No map,
cache, mask, queue or size-dependent measurement contract changed.

Before/after AST uses the existing audit Package parser. Native production249,
tests467; dependency Toad production288/tests403/tools40: no parse omissions.
Lexical sites do not resolve arbitrary external dynamic overrides. Original
Screen/Compositor/Widget owners and Toad viewport/anchor hooks were read.

One matched source App run used Toad437e/Core574 with the changed native source,
508 widgets/10 tabs, no provider. It exited0 with empty stderr. Ancestry visits
fell2746→1242 (left) and3230→1166 (right); empty deferred-region work fell from
~0.8–1.3ms to~0.001ms. Overall medians41.8/47.4ms do not establish an improvement
over the original43.8/41ms. This is a small removed cost, not solved latency.

The original six-check batch produced5PASS and one preserved failure: its
callback test expected the Screen to wait inside an admitted async callback.
The existing control now asserts the actual sender task, preserved callback
order and completion inside a later batch after original publication admission.
That changed control alone passed1/.26s; the other five were not repeated.
MessagePump.call_after_refresh and merged#75 own this lifetime. No production
callback rule changed. The five existing controls cover actual batches, held
subtree geometry/hits/callbacks, inline publication and translucent backdrops.

RESULT.json references the exact original/new profiles and App logs. No
installed pin, public runtime or frozen original evidence changed. The App
fixture cleaned its authored roots; no child operation is left running.
