# U5: original terminal model and native projection

Source begins at merged U2/current main8b81122c. Same isolated checkout and existing candidate holder; no new worktree/environment/native copy.

TerminalState already owns the ANSI stream, both buffers, cursor/modes, width/height, and write deltas. It imports Textual event/Content/Style/Color despite those being presentation and input boundary dependencies. The native Terminal separately stores width/height and repeats80x24 defaults; TerminalExecution and SurfaceBinding repeat those defaults again.

Reuse the original TerminalState/LineRecord/Buffer and Rich styled text/color owners. The Textual view uses its existing Content.from_rich_text/Style.from_rich_style boundary. Keep original PTY/cancellation lifetime unchanged. Detached geometry comes from the actual TerminalState; attached surface applies observed geometry through that owner, no second dimensions record/default policy. Native key events are decoded at the view into the existing terminal key method's primitive inputs. Preserve external ANSI/key contracts, line deltas, reflow, selection and cursor paint.

Read whole model, parser, style and projection callers through the existing NRA AST parser first. Migrate all consumers and delete replaced frontend dependencies, geometry fields and policy copies together. After one coherent source checkpoint, batch affected terminal contract/large stream and actual installed ACP real-PTY detach/reattach verification. No paid/provider request needed for the affected terminal-only journey. U4 view registration and unrelated viewport work remain separate.
