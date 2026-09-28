# T3 command and discovery closure

Own checkout: /home/ts/wt/toad-t3-commands-sol-20260928. Existing PR120 reused.
Recovered predecessor cccbe4a, seven tracked modifications and untracked
mcp_declarations.py; predecessor files untouched.

Implemented:
- SlashCommand reuses core Command/DeclaredFamily. Concrete commands own spelling,
  help, typed argument parsing and behavior. Completion derives from members.
- Deleted the maintained builtin roster, eleven-way Conversation dispatch, seven
  self.agent capability probes and the hard-coded SlashComplete demo roster.
- ACP advertised commands become typed instances at their external boundary.
  Local declarations own display/execution on collisions; native commands still
  pass to the established agent submission path.
- ThreadCommand projects existing ThreadAction declarations without a second
  registry or copied tool metadata. Contextual UI actions own copy/pin/close/
  any-mode. Both pointer menus and slash suggestions derive from these owners.
- Deleted sidebar action maps/mutations/message wrapper/handler and obsolete
  thread/channel/view menu builders. Generic Textual menu lookup remains its
  external input boundary. Exact open target is used, independent of sidebar
  selection. Execution rechecks route/state; unavailable actions are consumed
  visibly instead of becoming user messages. Channel member pin has an explicit
  optional @member argument and validates membership.
- DM/channel simple prompts now expose SlashComplete. Local commands can execute
  before model readiness. Shell/path/model extras remain restricted to agent views.
- MCP scope/status decode once into declarations. Deleted status roster and state
  comparisons; MCP/action-modal buttons use Textual selector declarations.

Actual evidence (provider-free, isolated owned stores):
- commands-acp-mounted.log: fresh ACP SDK producer -> real JSON-RPC validation ->
  mounted advertised completion; collision and forwarding; declaration insertion;
  real agent/DM/channel prompt submission; pointer/slash labels and target parity;
  archive, stale availability, channel/member pin and any-mode; history unchanged.
- archive-family-current.log: new ThreadAction declaration archives via actual
  mounted menu while retaining wire, goals, identity, transcript and saved session.
- stop-current.log: responsive typing/navigation, duplicate suppression, surviving
  view closure, and visible failure. Slow owner shutdown is intentionally injected
  only for this timing/error behavior; this is not native backend readiness proof.
- command-guards.log + actions-guard.log: retired rosters/dispatch/probes absent.
- mcp-native-parent-current.log: real installed native689 MCP package approve/
  allow/ask/deny, stale refusal/cancellation, mounted inventory, child cleanup pass.
- inventory-format.log: external strict DTO/redaction/trust/rejection contract pass.

Current test command:
PYTHONPATH=src:/home/ts/wt/comms-acp-saved-session-startup-20260928/src
TMPDIR=$PWD/.artifacts timeout60
/home/ts/.local/share/agent-comms/runtime-round2-final-20260928/bin/python
 evidence/t1/run_consumer.py tests/command_family_pilot.py

T2 integration contract read from Dalton's current paired tree:
update_project(path:str)->str; update_goal(action:str,text:str)->Goal|None;
compact_context(instructions:str|None)->dict; get_goal_snapshot()->tuple;
get_goal_history and get_input_delivery currently retain existing signatures.
T3 adds no extension codec. Parent must integrate final T2 request/snapshot records
into existing Conversation input-delivery/goal/compaction handlers before calling
combined T2/T3 caller closure done. Direct subagent messaging tools are unavailable
in this fork; authoritative source/checkpoint was inspected read-only instead.

D22 already live; no migration tools, live root, route, launcher or owner changes.
No CI wait or paid calls. T3 command/discovery batch is independently reviewable;
combined T2 final caller/type acceptance remains outstanding.
