# Current installed browser-serving closure

The existing browser pilot completed with exit **0**, unchanged, against the
default-selected installed runtime254. Actual Toad is
`187f380ee1fa6358f16020ace38fa42e11f01670`, Core
`e191bcf44c292dfedc5b8b62b2b503f06de3ae7b`, Textual
`6b5895fa0a72aeec2aeaef7206d5debfa0c1803c`, SDK 0.12.1 and native593. This
receipt does not cover a subsequent activation of backend476 or Toad266.

The original worktree had been removed. Its surviving branch was restored at
`$HOME/wt/toad-web-completion-20260928` and normally fast-forwarded to main
`d0349869466fbb054fcb00a8377eda80c813b104`. No product or test source changed.
Existing Playwright and pyte dependencies were appended after installed
packages in the parent pilot only. The CLI/server/Toad/ACP children used the
actual selected installed interpreter and packages without a source overlay.
An initial retired-API suspicion was retracted after inspecting the actual
installed `Messaging.initialize_private_initial_protocol` declaration.

One continuous existing pilot verified:

- Unauthenticated, forged Host, wrong/non-ASCII token, missing/null/foreign
  Origin, static and download requests reject before starting Toad children.
- Bootstrap redirects to a token-free URL with HttpOnly/SameSite=Strict.
- Ordinary `serve`, `run --serve` and `acp --serve` start real installed Toad
  children, render in actual headless Chromium, and respond to browser F2 by
  displaying the native Settings screen.
- Actual ACP initialize and session/new succeed; no session/prompt is sent.
- Two loopback ports retain independent authentication, including a reload.
- The existing real Textual delivery child streams the exact 150,000-byte
  payload through the vendor WebDriver and route with protected headers.

The ACP Ready view, ACP Settings view and Store PNGs were personally inspected
and are readable. These are browser-rendered frames, not DOM-only first-byte
checks. Keyboard evidence is F2-to-Settings, not the complete editor/focus
matrix. File delivery proves the existing transport; it does not invent an
otherwise absent Toad download action.

All fixture roots were disposable private roots under `$HOME/wt`. The original
pilot cleaned its servers/browser/children and roots; a post-run scan of the
exact attempt attestation found **zero remaining processes**. No model calls,
public-root writes, live user inputs, restarts or uncertain replays occurred.
The borrowed dependency environment was not changed.

[The receipt](current-installed-20261001-receipt.json) preserves exact runtime
identity, raw hashes, actual gate output, cleanup and reviewed-frame names.
Protected evidence remains under
`$HOME/.cache/agent-scratch/browser-serving-current-20261001`.
This contribution changes two evidence files and deletes **0 production
lines**. No code-bearing defect or further unchanged gate is asserted.
