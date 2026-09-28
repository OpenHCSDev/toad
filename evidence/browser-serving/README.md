# PR50 installed acceptance

## Delivered scope

Authenticated loopback serving is the existing `serve`, `run --serve`, and
`acp --serve` path. No second server, vendor patch, compatibility path, or new
enablement flag was added. The vendor owns routes and child transport; Toad owns
one endpoint/authentication boundary and the `BrowserAdmission` ABC with rejected,
bootstrap, and authenticated cases. External headers/credentials are decoded at
that boundary; cases dispatch through their common contract.

Actual runs caught and fixed eager `ToadApp`/renderer startup before authentication
in `run --serve`. Current-main integration also exposed the stale `.value`
access on the now-string CLI renderer argument in `acp --serve`; explicit and
default renderer forwarding use the current declared renderer family unchanged.
Wrong Unicode credentials return 403, rather than crashing constant-time comparison.

The predecessor's 227 mock-only test lines were deleted. The new browser pilot
and 37-line real Textual file-delivery child exercise real processes and protocol
transport. Their larger test surface covers child startup, three CLI modes,
Chromium keyboard/rendering, ACP initialization, and streamed delivery that the
mocked tests could not establish. The previous inline admission implementation
was replaced, with its superseded code retained only in Git history.

## Integration and installed stack

- Main integrated: `67ddc9e606ff7a9ce59a63df5227f1d1fb8f536b` (Toad125, including
  T2/T3/T5/T6 and ViewportPresentation). Original PR50 history is preserved.
- Product candidate: `014c2db` in this PR; later changes only add receipts/docs
  and propagate the test harness's cleanup attestation to private children.
- Comms pin: `853630552df22e16106a016ab24dfa70f5538ae5`.
- Textual pin: `16ede007c34bec893b2dbedb3999223381129678`; textual-serve 1.1.3.
- Toad was wheel-installed in this worktree's own venv, with no source overlay.
  `installed-imports.json` records actual import/installation origins.

## Results

- `python -m pytest -q tests/browser_serving_pilot.py`: **1 passed in 38.62s**.
  `pytest-browser.txt` and `installed-browser.txt` are its receipts. System
  Chromium displays real Store and ACP screens and F2 opens actual Settings.
- Real Comms ACP `initialize` and `session/new` completed; the session/new result
  is retained in `actual-acp-initialization.txt`. No `session/prompt` was sent,
  no model response was synthesized, and no paid provider call was made.
- Missing/wrong credentials, non-ASCII credentials, forged Host and
  missing/null/foreign WebSocket Origin reject before Toad children start.
  Valid bootstrap redirects immediately and sets HttpOnly/SameSite=Strict.
  Index/static/download routes are protected; same-browser ports coexist.
- Real Textual child sends a 150,000-byte file through the vendor WebDriver and
  AppService. Unauthorized download rejects; authorized stream returns exact
  content. Prepared download and WS101 headers include no-store, no-referrer,
  frame-ancestors none and DENY.
- Focused settings/T6/L0A/terminal deletion guards: **4 passed, 43 deselected**.
- Shared per-class debt ratchet against current main: exit 0, **no positive
  comparable deltas**. Full output is `debt-ratchet.txt`.
- Ruff and `git diff --check` pass. CI is deferred; no full-suite claim is made.

The earlier failing evidence is retained, including the actual unauthorized
child-start failure and two test-harness integration errors corrected before
the final pass. The browser screenshots show actual installed canvas output,
not a mocked renderer or DOM-only first-byte indicator.

## Boundaries and cleanup

The ACP root/history/settings were fresh private roots under `~/wt`; only the
installed native package/default-route declaration was read. Tests sent no input
to live sessions. File-delivery acceptance uses a real Textual child, not a
claim that an absent Toad download action was exercised. Browser acceptance
covers startup/connect/authentication/rendering/input, not a paid model turn.

All owned browser servers, child processes, ACP workers, short private roots and
disposable test artifacts were cleaned after completion. Retained evidence is
under 1 MB; the reviewable worktree/venv remain persistent under `~/wt`.
Parent owns merge and live installation. No shared checkout or live config was
changed, and no server was published outside loopback.
