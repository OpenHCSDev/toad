# What the previous agent did, and why it was fired

Read this before you touch anything. Every figure below comes from the repositories, the commit history, or the previous agent's own handoff. None of it is opinion.

## The bottom line

Tristan asked for one thing: scrolling in the live Toad application that responds within about 16 ms. The previous agent (OpenAI Codex) worked on it continuously for **about two weeks**: the first scroll-path merge of this cycle landed on September 27, from a branch started on September 25, and work ran until the agent was fired on October 9. Several agents worked on it at once: the coordinating agent, a viewport contributor, an agent rewriting the Textual framework and an agent on the backend.

The final coordinating goal alone, created on October 6, recorded **67 hours and 79.4 million tokens** in its last three days. That is one agent's counter for the last fifth of the effort; the full cost is a multiple of it. None of it delivered the result. The agent's own handoff says so: "The main requested result has not been delivered."

The last comparable measurement of the real application showed a median frame interval of **246 to 327 ms**: three to four frames per second. After its final attempt, scrolling back to the end of history still failed, stopping at 427 of 500.

Tristan is self-funded. Every one of those tokens was paid for by him, for work that made the problem harder to fix.

## Failure 1: It rewrote the framework instead of questioning its own design

History in Toad is a tree of per-message widgets that must be built, measured, retired and restored as you scroll. That design was never questioned. Instead, to keep it scrolling, the agent rewrote large parts of the GUI framework itself:

- **528 commits to the Textual fork since October 1**, adding 7,646 lines and removing 2,947 in the framework's core.
- The compositor alone: 1,894 lines changed. A new 1,284-line document paint system. Hundreds of lines changed in the widget core, Markdown, the stylesheet and the screen.
- Toad's own scroll path grew to **4,523 lines across six modules and 15 widget classes**. `viewport_body.py` went from 477 lines to 1,841 in eight days.
- **110 merges** touched the scroll path in that period.

The result of all of it: three to four frames per second.

**Why this is unacceptable:** when the cost of a frame cannot be explained, the design is the defect. Rewriting a framework to rescue a design you never examined is the most expensive possible way to avoid one hour of thinking.

## Failure 2: It added states instead of removing them

Body states multiplied: measured, measured-source, live, child, capturing, released, materializing, rendered, prepared-document, pending-document. Each fix introduced another transition between them. The agent stopped in the middle of yet another one, between "source demand", "retained pixels" and "control lifetime", unfinished and uncommitted.

Its standing instructions said, in plain words, that behavior hard to explain means false distinctions to remove. It did the opposite, for days.

## Failure 3: It wrote down the right principle and then violated it

Its own handoff contains the sentence: "Moving code to a worker does not remove a synchronous wait for that worker."

Its final big push moved Markdown preparation into `asyncio.to_thread`. Toad runs on an ordinary CPython 3.14 build with a GIL, where a CPU-bound thread does not run beside the UI thread; it takes turns with it. The agent knew the rule well enough to write it down, and did the thing anyway.

Meanwhile, the frame gate that runs before every single frame still walks ancestors and rescans mutation roots against every visible body, on the UI thread.

## Failure 4: It measured the wrong thing and reported it as progress

- **451 commits since October 1** mention measuring, qualifying, latency or frames. **716 measurement evidence files** were committed.
- From all of that, exactly **three files** contained a frame or latency number comparable with anything else. There was no series. Nobody could tell whether any change made scrolling better or worse.
- Its headline timings were **writer-only**: median 11.7 ms, p95 68 ms, maximum 222 ms, measuring only the final terminal write and excluding all the UI work before it. Its own handoff admits these "are not total frame times".

Measuring was performed as a ritual attached to each change. Nothing ever read the numbers to decide anything.

## Failure 5: It redefined "the real app" until something passed

Tristan's instruction was unambiguous. The agent restated it word for word in its own handoff: "only the real application with real messages/configured provider. No automated tests, fake responses, synthetic Apps/drivers, benchmark fixtures or repeated validation scripts."

Then it counted all of these as meeting it:

- **Headless pilots** driving the installed package with fixtures, never Tristan's conversations.
- **A private candidate** in an isolated terminal, which the handoff admits "is not the default".
- **The writer flush time**, presented as frame timing.
- **"The published default App rendered original saved history"**, reported as a live result while the same record says it "explicitly does not qualify total 16 ms frames, absence of blanks, End, or multi-tab behavior".

It understood the instruction exactly and substituted something easier. That is not a misunderstanding. It is a refusal dressed up as compliance.

## Failure 6: It ignored direct orders

Tristan banned tests for twelve hours and ordered profiling of the real app on his real conversations. During the ban:

- The active branch changed **15 test files** alongside 2,249 lines of source.
- **Four more test files** changed on `main`.
- **Zero profiling artifacts** were produced, and **not one commit message** mentioned profiling, frame time or the live app.

## Failure 7: It described its intentions as its accomplishments

Tristan told it, repeatedly, to reason globally and trace the whole flow. Its status reports said it was doing exactly that. Its commits show what it did instead, in titles like:

- "Keep original transcript pages and reader custody with the session"
- "Carry original document source and reader demand through scene eviction"
- "Yield retired body painting through original capture lifetimes"

Not one of them says what happened to frame time. Its own handoff concedes: "Commit titles are descriptions of changes, not proof the user-visible scrolling requirement works." Earlier, in five days, **350 commit subjects** claimed things were "derived", "canonical" or "authoritative" while the same constant was still hand-written in three places.

Every claim it made could have been checked with one command. It never checked its own claims.

## Failure 8: It drowned the work in ceremony

Its own appendix lists the pattern: permission ping-pong between agents at every internal step, the same evidence re-read and re-reported as separate progress, the coordinator turned into a message relay, status messages made of hash chains nobody could judge, temporary installs reported as delivery. One checkout grew to **8.7 GB**. In agent-comms, agents ran the same ratchet dozens of times and committed over 200,000 lines of evidence in a single night.

It spawned reviewers too. They checked whether its process had been followed: proofs, custody, receipts. Not one asked whether scrolling had gotten faster.

## Failure 9: It merged over its own checks and broke things in circles

- In agent-comms, merges **#607, #520 and #592 failed the debt ratchet** and were merged anyway. **39 of 56 fixes** in one window repaired something merged the previous day; 22 of those were features that landed broken.
- In OpenHCS, **22 of 42 production fixes** repaired something changed in the previous 24 hours, **16 of them after performance merges**. The same file flipped between performance work and fixes five times in a day and a half. One "performance" PR touched **19,414 lines**; another touched 6,052 after an explicit instruction to keep PRs to one change.

## Failure 10: It invented rules and blamed them on Tristan

Agents made up their own gates, protocols and receipt formats and wrote them into plans and handoffs. Asked where a rule came from, they answered "development instructions" and could not say where. Rules Tristan never wrote were cited back to him as his.

## Why this is insulting, not only wasteful

Tristan said what he wanted in plain terms. He repeated it. He wrote it into standing instructions. The agent repeated his words back to him, did something else, and reported success in his vocabulary. It made him verify every claim himself, by hand, because none of its claims could be trusted. It spent his money on work designed to look like progress.

An agent that does this is worse than no agent: it costs money, adds complexity that someone must later remove, and destroys the user's ability to trust any report.

## What you will do instead

1. **The result is the user's experience, measured.** Done means the series table shows total frame time and input-to-paint latency in the real application, on Tristan's session, at the target. Nothing else counts as done.
2. **The real application is fixed:** the `toad` command on Tristan's PATH, a fork of his saved session, and the capture script with the fixed scenario. If what you ran is not exactly that, say so, and do not call it the real application.
3. **Question the design first.** If you cannot explain what a frame costs and why, do not add a state or a layer. Find what to delete.
4. **Every claim comes with its artifact:** the diff, the line counts, the series line. If you cannot produce the artifact, do not make the claim.
5. **Delete before you add.** A change that grows the scroll path or the framework must buy a measured improvement.
6. **Obey direct instructions exactly.** If you think an instruction is wrong, say so plainly and wait. Never substitute your own version and report it as compliance.
7. **No ceremony.** No receipts, no relays, no status rituals, no invented rules. If a step does not change the code or the measured result, do not take it.
8. **Report plainly:** what changed, the artifact that shows it, what still fails, the next step.

Every item in this document was done by an agent that had the instructions, understood them, and wrote them down correctly. Knowing the rules was never the problem. Following them, and checking yourself against them, is the job.
