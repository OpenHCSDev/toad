# T3 Sol takeover

Own checkout: /home/ts/wt/toad-t3-commands-sol-20260928.
Recovered predecessor committed cccbe4a and all seven tracked modifications plus
untracked src/toad/mcp_declarations.py from toad-t3-commands-20260928.
Predecessor files are untouched. Recovery patch retained locally, not published.
Existing PR120 branch reused; no competing PR.

MCP scope/status names and behavior now belong to shared DeclaredFamily members.
The duplicate status roster and state comparisons in inventory, decisions and
mounted screen are deleted. External version-2 package format remains exact.
Inventory and action-modal buttons use Textual selector declarations; identifier
switches and decision lookup map are removed. Core extension codec is untouched.

Evidence in this directory:
- inventory-format.log: strict package DTO/redaction/trust/rejection pilot passed.
- actions-guard.log: predecessor thread action deletion guard passed.
- mcp-native-parent-current.log: mounted Textual inventory plus real installed
  package approve/allow/ask/deny, stale-snapshot refusal and controller cancellation
  passed; child processes reaped. No provider or MCP server was started.
- earlier failure logs retained: initial runs selected older core source; entry-store
  package has owner-read-only root and old helper requires mode700. Current native
  package689ce paired with current integrated core passed. No live permissions changed.

Actual successful command:
AC_NATIVE_COPIED_PACKAGE=/home/ts/.local/share/agent-comms/native-current-689ce4b5d0592b9a/node_modules/@earendil-works/pi-coding-agent
PYTHONPATH=src:/home/ts/wt/comms-acp-saved-session-startup-20260928/src
TMPDIR=$PWD/.artifacts timeout60 runtime-peer-close-20260928/bin/python
 evidence/t1/run_consumer.py tests/mcp_decision_pty_pilot.py

Remaining required T3 closure: declaration-owned slash command family and argument
parsing, ACP advertised-command boundary, all Conversation capability probes,
shared command discovery53 across agent/DM/channel contexts and mounted submission
acceptance. Parent must supply T2 merged consumer contract/checkpoint; no duplicate
extension decoder is introduced here. Existing thread-action family is retained.
This checkpoint proves MCP sub-scope only, not full T3 completion or deployment.
