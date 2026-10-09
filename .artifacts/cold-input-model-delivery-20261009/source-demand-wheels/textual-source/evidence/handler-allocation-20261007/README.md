# Handler lookup allocations

The existing metaclass already collects decorated declarations and parses selectors. No declaration registry or event cache is needed. Named handlers must remain live: an awaited decorated handler can replace the named handler that follows it. C3 order, instance binding, selectors and bubbling remain runtime work.

The original lookup constructed an empty list on every missing decorated-handler match, including each message ancestor in each decorated class table. It also allocated a duplicate-tracking set even when no decorated candidate existed. Lookup now uses the immutable empty tuple on a miss and creates its set at the first decorated candidate. Existing declaration lists and post-yield duplicate accounting are unchanged.

The existing refactor-audit Package parsed 250 production modules without omissions. `_get_dispatch_methods` is used by `_on_message` and idle delivery; both use the same changed implementation. No other declaration-table writer was found beyond `_MessagePumpMeta`; dynamic class mappings and decorated lists remain live.

Fourteen affected original decorator/message checks passed in 2.18 seconds, including inherited duplicate suppression, C3/private precedence, selector matching and live replacement during awaited dispatch.

One original channel App check passed: 160 authored private messages, 20 arrivals, focused history paging; sequence113 to73, 88 mounted rows, no App error, empty stderr. Installed Toad/Core came from viewer-cut-and-header-delivery-20261007; only native source was supplied. The installed message-pump diff consists exactly of these allocation changes. No provider, installed-package write or public operation. Original fixture teardown joined its private work; individual child birth identities were not collected.

Raw result/profile/logs: /home/ts/.cache/agent-scratch/native-handler-allocation-20261007. Previous profile: /home/ts/.cache/agent-scratch/installed-viewer-cut-header-20261007/ui.pstats.

Profiling recorded229908→214884 lookup calls, own time.9755→.9351s and inclusive1.5684→1.4606s. Own time per invocation4.24→4.35microseconds did not improve. Heartbeatp95 went46.13→35.11ms, maximum182.39→227.40ms; arrangement workload and final scroll position differed. These runs do not establish a reliable responsiveness or overall speed gain. Layout remains substantial required work.
