# Adaptive viewport preparation

Owner: TC2 continuation. Integration owner: Heisenberg, PR213.

Scope: extend existing DirectionalPreparation, DocumentViewport and shared PreparationRuntime demand scheduling. Prepare farther ahead with measured scroll velocity and direction; cancel stale lookahead on reversal/idle; End prepares only the destination viewport. Preserve bounded worker/cache resources. No competing tab cache, source lifetime or presentation state.

Acceptance: actual installed saved-history journey in isolated Xvfb/st with held PageUp, PageDown, reverse PageUp, End and idle. Correlate recording action markers with profiler samples before attributing CPU hiccups. Focused local contracts support this journey; they do not replace it.

Pair: integrate current Toad main normally. Parent coordinates the reviewed Core/Textual/native versions and installation. Native fixture slot is serial and currently with Einstein.

Work in progress. No readiness or activation claim.
