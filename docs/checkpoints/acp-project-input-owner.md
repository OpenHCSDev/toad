# ACP project input ownership

This separate CLI change follows the completed context explorer309. It reuses the same checkout and installed dependencies.

The original `acp` command declares positional PATH and `--project-dir` with the same Click destination. Click parses options first, then arguments; an absent PATH overwrites the supplied option in the parser's original destination before parameter conversion. The actual isolated st launch then used the checkout cwd and the saved owner refused it. Supplying the original registered working directory as positional PATH loaded the same saved thread correctly.

Owner: the original Click command boundary. Keep both intentional input spellings with distinct raw destinations; resolve them once into the existing project_dir parameter consumed by ToadApp and ACP browser command construction. The explicit option takes precedence when both are supplied. No environment override, alternate launcher or downstream saved-thread exception.

Source evidence uses refactor-audit's Package/Repository AST loader: 278 production modules parsed with zero omissions. Relevant consumers are ToadApp.__init__, normal ACP terminal startup and ACP serve-command reconstruction. Core's existing toad-comms launcher supplies the original registered worktree as positional PATH. Browser documentation and browser_serving_pilot supply the option. The latter runs with cwd equal to the option, which concealed the defect.

Implementation precedes verification. Finish with one bounded boundary check covering both spellings and their canonical serve/terminal result, then the affected installed CLI using the original saved thread from a different cwd. Preserve saved history and uncertain inputs; no provider input is needed. Context309's accepted source/native/return journey is not repeated.

Working source: AcpCommand extends the existing Click command and resolves its raw inputs after original parsing, before callback invocation. The flag has its own raw destination; it is consumed into the original project_dir slot, with original ParameterSource retained. ToadApp and serve reconstruction receive only that selected value. Actual Click boundary checks passed for positional PATH, long/short options, both argument orders with both inputs, and cwd fallback. No app, server, provider or owner was replaced by a test. Installed option-launch acceptance remains the final check.
