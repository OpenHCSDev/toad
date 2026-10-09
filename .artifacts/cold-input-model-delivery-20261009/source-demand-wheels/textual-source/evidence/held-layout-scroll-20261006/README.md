# Held layout requests during scrolling

Screen previously chose full layout whenever `_layout_widgets` was nonempty.
After a layout during a mutation, that same mapping intentionally retains
requests below the held roots. Compositor already preserves those roots' exact
committed geometry in both full and visible arrangement. Retained requests
therefore forced repeated full layout without being allowed to change their
subtree.

Screen now owns the existing hold classification in `_held_layout_requests`.
Scroll takes the original visible traversal when every pending member is held.
Requests outside the hold, including promoted auto-size ancestors, still force
full layout. The full-layout branch uses that same classification to retain
requests after arrangement. Release makes those requests actionable again.
An empty request mapping needs no mutation-root acquisition.

No placement, mutation-root, damage, callback, resize or renderer owner was
replaced. The original visible traversal still acquires retained reader paths;
Compositor still preserves exact held hit/paint geometry. No persistent state,
cache, timer, Toad change or publication exemption was added.

## Confirmation

The existing real App control now performs two scroll layouts while a mounted
child is held, verifies exact geometry/hits and pending requests, then admits an
outside request and verifies full layout. Original release applies the mount.
The original cut-cell, callback and overlap assertions remain. That control and
the inline/translucent controls passed: **3 passed in 0.57s**. The final empty
request shortcut was subsequently exercised by the source App below.

One original Toad sidebar source App completed with 508 widgets / 10 tabs,
exit zero and empty stderr. First-display medians were 35.1ms / 40.1ms, with a
112.1ms left maximum. This ordinary layout check does not measure the changed
held-scroll path or establish a reliable speed improvement.

Source: `before.json` parses native 249, Toad 288 and Core 324 modules with zero
omissions; `after.json` contains the native decision/consumer sites. Arbitrary
external dynamic mutation of private layout state remains outside this audit.

Raw App output and profiles remain under
`/home/ts/.cache/agent-scratch/held-layout-scroll-20261006/`.
The supplied live scroll profile identifies full/visible arrangement activity;
its transition groups do not establish call counts, CPU durations or which
pending layout requests caused any particular pass.

This is a source/native-framework qualification. Installed saved scrolling,
writer-gap reduction and overall smoothness remain unqualified. No provider,
package, artifact, public-owner or recorder operation occurred.
