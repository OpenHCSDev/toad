# Ordered native pointer admission

App originally selected every pointer target before the queued MouseDown handler
could establish capture. A queued move and release could therefore miss the press
owner, then its late handler left capture active. This is a source defect; it is
not proven to be the interleaving in closed physical02.

Message owns one pending dispatch completion. MessagePump._post_message_and_wait posts the original
message to its existing FIFO and releases completion only from the receiver which
still owns it. Bubbling transfers that custody through the original DOM queues;
the originating pump retains its own bubbled copy for later dispatch. A retiring
receiver releases its original delivery without cancelling children or replay.
App awaits this admission before resolving the next pointer packet. Screen and
Widget return the existing AwaitComplete resource; Pilot awaits the same contract.
Capture, release, selection, hit geometry, broker actions and disabled input keep
their existing owners. No second input queue, capture state or timed delay exists.

Native Input, TextArea and ScrollBar capture from their queued handlers. Toad
SidebarResizeHandle, SidebarSlider, GoalBar and Mandelbrot do the same. Ancestor
handlers retain ordinary bubbling. The awaited chain stops before the originating
App pump, which cannot await itself; its forwarded application-level event remains
on its original FIFO. This is target/DOM admission, not synchronous application
notification delivery.

Existing refactor-audit Package parsed 249 native production / 461 test modules
and 288 Toad production / 400 test modules, with zero omissions. before.json
contains 118 lexical owner/consumer sites. Dynamic overrides/factories remain a
semantic resolution limitation, not zero-by-omission proof.

Changed native checks passed: 33 in 10.45s through actual App/HeadlessDriver
packet ingress, direct and ancestor capture, delayed press, release-before-wheel,
Input/TextArea selection, filtered delivery, self-removal, original input messages
and queued selection/copy behavior. The first selection batch caught 80 redundant
selection rebuilds: original call_next flushed every newly awaited DOM delivery.
That early fallback is deleted; original copy/release/paint/refresh-callback owners
still flush the single pending projection. Final source retains all 80 mouse events
and exact mid-burst/final copy values. No new timer or selection state exists.

Two initial authored editor assertions incorrectly assumed an unpanned/unwrapped
substring; their expectation is now movement selection, preserved original text
and ended capture. Initial negatives stay in the tool transcript; final-checks.log
retains the coalescing refusal and qualified-checks.log the completed result. Parent owns recorder motion
acceptance; no physical run, installed pin, package or public runtime is changed.
Frozen e15 / physical02 evidence remains unchanged.

The first checkpoint broke the drivers' coroutine scheduling contract by changing
_post_message to a synchronous return. That negative is retained in Parent's
mounted.stderr. The original async _post_message coroutine and bool admission
contract are restored for all Headless/Linux/inline/Web/Win32 driver callers,
MessageTarget/EventTarget protocols, Markdown self-publication and input tests.
Awaited target completion is a distinct MessagePump operation on the same FIFO;
it does not change raw driver admission or add a queue. These callers are present
in before.json; the first checkpoint failed to read their scheduling requirements.

No physical02 causality or repaired physical motion is claimed. Parent owns the
matched application/recorder acceptance. All local checks are terminal, with no
provider, installed package, pin or public runtime operation.
