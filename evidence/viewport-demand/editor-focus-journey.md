# Joint PR227 editor-focus journey

Integration owner: Heisenberg227. Input-consumer diagnosis: Kepler.
This is a prepared journey, **not a reproduced failure or a PASS**.

Use the existing isolated Xvfb/st recorder on the coherent actual default
Toad/Core/Textual650/native pair. Its normal runtime-pin admission must pass;
do not override that guard to run a mismatched package. One capture only.
The current default-entrypoint gate is owned by the installation/integration
owner. No concurrent capture, provider call, public mutation or native replay.

Protect the real editor resources: use an owned `XDG_STATE_HOME` for this
capture, with a SQLite backup of the existing Toad state if the saved workspace
is needed. Leave the selected native route and original retained sessions
unchanged. Preserve the real user's DB, draft, cursor and undo. Verify the test
editor starts empty before typing. Use an existing fork child for navigation;
do not create a fork or submit any text.

## One continuous physical journey

Derive actual prompt/tab/roster coordinates from the initial physical PNG and
committed native geometry. Use xdotool physical clicks/keys through st, not
direct editor mutation or a simulated UI/protocol. Mark phases using the
existing recorder and observe its native screen/editor DTO.

1. Click the prompt; type `abcdef`. Verify the actual draft is `abcdef` and
   the empty selection is `(0,6)`.
2. Press Left twice, Backspace, Delete, Right. Expected draft: `abcf`, empty
   selection `(0,4)`. Capture after each key boundary if the result differs.
3. Click retained chat history, PageUp, then type a fresh `abcdef` suffix to
   exercise the existing printable-key autofocus. Apply the same edit-key
   sequence. Observe where the focus and each event actually land.
4. Physically click an existing peer and return A/B/A. Check the original
   draft and cursor were retained; perform the same suffix/edit operation
   after the return, without forcing focus through a diagnostic callback.
5. Open a channel using its channel-bar path, click its composer, perform the
   unsent sequence, then return to the existing agent and check its own draft.
6. Open an existing child thread and return to the parent through real tab or
   roster controls. Repeat editing in the returned composer.
7. Clear only these isolated test drafts with the actual composer control,
   verify no submission occurred, and close the recorder-owned TUI. The
   original native owners/input journal remain unchanged.

Never press Enter, Ctrl+Enter or Ctrl+Y: those submit prompts in Toad. Ctrl+A
is line start, not select-all, in the actual TextArea. Arrow Up/Down at an
editor edge intentionally invoke prompt history; use Left/Right and interior
multiline movement to distinguish that behavior from lost bindings.

## Read-only evidence and interpretation

`tools/performance/capture_state.py` now observes native `Screen.focused`,
its actual ancestor path and the object identity of each existing draft DTO.
It stores no product focus flag, cursor, binding cache or semantic authority.
The existing draft text/selection fields are retained. The diagnostic is a
snapshot and must not drive focus or repair it.

Correlate physical key markers with focused-object identity, actual editor
text/selection, selected logical view and terminal frames. If focus changes,
trace the actual caller; if focus remains on that exact editor while a key
fails, inspect native parser/binding consumption at that boundary. Do not
infer a Textual, terminal or deferred-autofocus defect from source alone.

Current source inspection: Textual650 derives its binding chain from native
`Screen.focused`; it is not a separate persistent binding-state mirror.
Workspace autofocus uses deferred native `Widget.focus()`. The channel's
mount/retry also requests prompt focus. These are investigation leads, not
proven defects. Conversation/layout consumer changes require Heisenberg's
consent. Open a scoped draft before a substantial production fix if a concrete
unowned defect is reproduced. Production lines deleted so far: **0**.
