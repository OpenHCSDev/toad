# First session: decide before building

Work in plan mode. Do not edit source in this session.

Read `docs/agents/CODEX-POSTMORTEM.md` first: it is what the previous agent did and why it was fired. Then read `CLAUDE.md`, then sections 3, 4, 7, 11 and 14 of `docs/handoff/HANDOFF-REPLACEMENT-20261009.md`. The previous agent spent about two weeks on scrolling, with several agents at once, without delivering it. It found real defects, but it kept adding states and machinery to a design it never questioned, and rewrote large parts of the Textual fork (compositor, CSS, widget core, a new document paint system) to keep that design scrolling.

Deliver three things, about a page in total:

1. **What one frame costs during a held PageUp, from the source.** Every piece of work between the key event and the terminal write: which owner does it, whether it runs on the UI task, and why it exists. Name the work that exists only because history is a tree of per-message widgets that must be materialized, measured, retired and restored.

2. **A design decision.** Compare finishing the stopped six-file working diff with replacing the per-message widget history by one line-based virtual document: the existing prepared strips, sliced by Textual's Line API so only visible lines are rendered, the approach Textual's own large-content widgets use, with widgets kept only for visible interactive controls and the streaming tail. For each option, state what would be deleted in Toad and in the Textual fork, what remains hard (selection, pointer interaction, custom grammar, reader position, End, tab return), and how we would know it worked. Recommend one, with your reasons. If neither is right, say what is.

3. **A baseline plan.** The exact capture you would run with `tools/performance/capture_live.py` on the fixed scenario in `CLAUDE.md` to measure total frame time and input-to-paint latency today. Do not run it until I approve.

Keep it plain. No status ceremony, no hash chains. If something in the handoff is wrong, say so.
