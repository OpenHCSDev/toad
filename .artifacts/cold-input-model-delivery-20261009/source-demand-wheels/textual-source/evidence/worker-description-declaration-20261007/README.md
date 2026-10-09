# Worker descriptions without payload formatting

Worker launch previously walked every decorated argument through repr, joined
the full result, then truncated it in Worker. WorkerManager independently used
repr(work) for a missing or empty description, including functools.partial and
its bound payload. These are diagnostic values, not execution inputs.

The work decorator now derives its default description once from the callable
declaration. Ordinary functions use their qualified name. Supported named partial
declarations use the explicit name when they have no qualified-name attribute.
No arguments or keyword values participate. The original partial(method, *args,
**kwargs), execution flags and worker lifetime remain unchanged.

Worker owns the direct-launch default: description=None means use the worker
name. DOMNode.run_worker and WorkerManager forward that value instead of making
another diagnostic decision. Explicit strings, including empty strings, stay
explicit; the existing 1000-character truncation stays with Worker. Worker repr
and StateChanged retain safe string diagnostics without formatting the work.
API: direct run_worker / WorkerManager / Worker description defaults are now
str | None = None. The work decorator already used that distinction.

61 original worker/decorator/manager/context controls passed in 1.99s. The final
two affected controls passed in .27s after preserving named partial declarations.
Real App workers verify default and explicit descriptions, zero payload and
callable repr calls at launch/display, async/thread identity delivery, unchanged
truncation and joined completion. No mocks, provider calls or private packages.
No installed ContextExplorer or live latency acceptance claimed; Parent owns
that application check and publication.

source.json records original declaration/consumer sites using the existing
refactor-audit Package parser. Native and Toad parse without omissions. Worker
description consumers are diagnostics; no lifecycle decision uses the former
argument dump. Arbitrary external subclasses/callable attribute behavior is not
resolved by lexical sites. Explicit user descriptions remain caller-supplied.
Native supplies no automatic payload representation or new cache/registry.
