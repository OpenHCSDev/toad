# Callback binding and original arity

The existing `count_parameters` owner serves `invoke` and reactive watchers.
Python bound methods expose attributes on their original function. Storing a
bound arity there therefore makes later unbound counts wrong; looking up that
hint before deriving binding also makes bound counts wrong when the unbound
function was counted first. Partial counting bypasses the underlying owner.

This independent API correction keeps the existing function hint as raw
arity, derive binding before reading it, and derive partial arity through the
same original owner. Python `MethodType` declares actual binding; built-in
callables retain their own signature and need not support writable hints. No
new cache, callable wrapper or state owner is added. Both `invoke` and reactive
watchers consume the corrected existing API. Native viewport projection PR63
stays frozen and independent.

The claim that every repeated bound count inspects its signature was incorrect:
CPython's method attribute lookup delegates to the original function. That
performance claim is withdrawn. No frame-time gain is claimed here.

The complete native before/after AST parses 249 modules without omissions;
`owner-consumers.json` records the original hint writes and count consumers.
The final source batch passed seven controls in 0.38 seconds, including both
discovery orders, partial binding, uncacheable callables, and actual native App
reactive dispatch followed by unbound/partial invocation. See `SANITY.json`.
This qualifies the source API; no installed package, wheel, recording or provider
purpose has been used. Dynamic external metadata is outside AST resolution.
