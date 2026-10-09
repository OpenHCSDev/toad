# Native handler lookup

The native metaclass already collects decorated functions and parsed selectors
at class construction. Unlike Core MroDispatch before its refactor, native
dispatch does not scan every method on every event. A new declaration registry
would duplicate that owner and could freeze legitimate method replacement.

The remaining repeated work is inside MessagePump._get_dispatch_methods:
class.__dict__ was acquired up to three times per owner, the private handler
name was constructed per owner, and the message MRO was filtered even if no
decorated declaration used it. Now each owner uses one live mappingproxy, the
private name is prepared once, and the captured message MRO is filtered only
when decorated handlers require it. No persistent state, event cache or wrapper.

The original full message MRO is captured before the first yield, preserving
its invocation lifetime even if classes change while a handler awaits. Class
mappingproxies remain live: replacements during decorated delivery are visible
to the following naming lookup. Decorated declaration lists, their duplicate
suppression and post-yield ordering remain original. Every invocation still
binds the actual function to its current instance and class. Selectors still
read current message attributes and match the current widget. Default-action
checks, namespace naming, private/public precedence and bubbling are unchanged.
Native inheritance deliberately calls declared handlers across C3 owners;
Core-style unannotated masking was not imposed on this different contract.

Parent weak references and ancestor traversal remain live DOM/lifetime answers,
not class declarations. This change neither freezes them nor changes readiness,
geometry, publication, queues or pump task custody.

23 affected checks passed in 2.36s: existing decorator, message handling and
message-pump controls plus one real App C3/private-precedence/dynamic replacement
control. That control changes the named handler while the decorated yield is
suspended, then exercises another App instance to verify fresh binding.
controls.log retains the terminal result. No provider, package, public App or
installed pin operation. No latency gain or CPU attribution claimed from the
original sampled stack-transition groups. Parent owns matching App recording.

source.json uses the existing refactor-audit Package parser for native and Toad
declarations/lexical consumers, with no parse omissions. Dynamic external
metaclasses that fabricate dictionary views cannot be inferred from lexical
sites; the native owner uses real class mappingproxies. Arbitrary mutation of
decorated declaration lists remains the original live-list behavior. No class
method or annotation supply was frozen.
