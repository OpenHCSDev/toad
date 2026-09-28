# T3: Commands and actions

**Head audited:** Toad fork `main` at `43e57c9` (#108). **Rules:** [00-RULES.md](00-RULES.md). **Origin:** both. **Step 3,** after T2. Uses agent-comms' `Command` and `DeclaredFamily` (TD1). Pattern IDs refer to the refactor-audit skill's catalog.

---

## What is wrong

**Slash commands are declared once and implemented somewhere else (MEMB-1, IMPL-1, IMPL-7).** `Conversation._build_slash_commands` (around `conversation.py:2398`) declares names and help for completion:

```python
SlashCommand("/model", "Choose this thread's model"),
SlashCommand("/toad:about", "About Toad"),
...
```

and `Conversation.slash_command` (146 lines, `conversation.py:3283`) implements them by comparing bare names, eleven ways, parsing each command's arguments inline:

```python
if command == "login": ...
elif command == "project":
    if path.startswith(("'", '"')): ...
elif command == "goal": ...
elif command == "toad:clear": ...
```

The two copies are joined only by spelling, with and without the slash.

**The agent is probed for capabilities by name (BOUND-7).** `slash_command` and its neighbours check `hasattr(self.agent, …)` for seven methods: `compact_context`, `edit_goal`, `get_goal_history`, `get_goal_snapshot`, `get_input_delivery`, `update_goal`, `update_project`. Under TD3 every agent is an agent-comms agent, so each probe tests something always true.

**Thread actions spell agent-comms' tool names in four places (MEMB-3, IMPL-1).** `comms_start`, `comms_stop`, `comms_archive`, `comms_delete` and `comms_ack` appear as:

- a dict of pending labels (`app.py:1577`: `"comms_start": "Starting…"`);
- an `if action == …` chain choosing each action's notification (`ToadApp._run_thread_action`, `app.py:1586`), reading results by string key (`result['launched']`);
- menu entries (`widgets/comms_menu.py:243`: `("comms_ack", acknowledge_label)`);
- a dict of lambdas and a name comparison (`widgets/comms_sidebar.py:1415-1420`).

The action then travels as a string into `run_selected_write`, which invokes the agent-comms tool of that name.

**The MCP inventory screen dispatches on button identifiers** (`identifier == "close"`, `"refresh"`, …) and compares row states as strings (`row.scope == "project"`, `row.status == "approved"`).

---

## Target

### Slash commands own their name, help, arguments and behaviour

```python
class SlashCommand(Command, affix="Command"):
    help: ClassVar[str]

    @classmethod
    def parse(cls, arguments: str) -> Self: ...        # typed arguments, parsed by the command
    async def apply(self, conversation: Conversation) -> bool: ...

class ToadLocal:
    """Capability: Toad's own commands, spelled with the toad: prefix."""

@dataclass(frozen=True)
class ProjectCommand(SlashCommand):
    help = "Set this thread's project directory"
    path: Path

@dataclass(frozen=True)
class AboutCommand(SlashCommand, ToadLocal):
    help = "About Toad"
```

- The completion list is derived from the family; `slash_command` becomes: find the member by name, `parse`, `apply`. The 146-line dispatch and the hand-written list are deleted.
- Commands the agent advertises over ACP (`available_commands_update`, an external format) become `AgentAdvertisedCommand` instances at the boundary, forwarded to the agent; they join the same completion list.
- The seven `hasattr` probes are deleted: the methods exist on every agent this fork serves.

### Thread actions are one family

```python
class ThreadAction(DeclaredFamily, affix="Action"):
    command: ClassVar[type[agent_comms.Command]]      # the agent-comms command it invokes, by class
    pending: ClassVar[str]                            # "Starting…"
    menu_label: ClassVar[str]

    def completed(self, result: CommandResult) -> str: ...   # the notification, from a typed result

class StartAction(ThreadAction):
    command = agent_comms.StartThread
    pending = "Starting…"
    menu_label = "Start"
    def completed(self, result: StartResult) -> str:
        return f"{'Starting' if result.launched else 'Already running'} @{result.thread}"
```

The labels dict, the `if` chain, the menu tuples and the lambda dict are all derived from the family; `run_selected_write` takes the command object instead of a name.

### The MCP inventory screen uses Textual's own registry

Button handlers become Textual's `@on(Button.Pressed, "#refresh")` declarations, the framework's registry for exactly this. Row scope and status decode once, from the pinned MCP package's inventory record, into families.

---

## Crossings

- **T2 first:** it moves the extension handling out of `Agent` and `Conversation`.
- **T5 in parallel:** thread actions appear in T5's files (`comms_sidebar.py`, `comms_menu.py`). T3 builds the `ThreadAction` family in a new module and converts `app.py`; T5 converts its own widgets to use it.

## Guards

In `src/toad/`: no comparison of a command name outside the command family; no `SlashCommand("/…")` literal outside it; no `hasattr(self.agent`; no `comms_…` action literal outside `ThreadAction`; no `button.id ==` comparisons.

## Tests

- **One family test:** every slash command parses an example and appears in completion; every thread action has its presentation.
- **One new-case test:** a test-only command appears in completion and runs, with no other edit.
- **Delete** tests of `slash_command`'s branches and of the thread-action dispatch.

## New-case experiments

- **A slash command.** *Today:* a completion entry, an arm in a 146-line function with inline argument parsing, sometimes a `hasattr` probe. *After:* one class.
- **A thread action.** *Today:* four places in Toad, all keyed by the same string. *After:* one class, beside its agent-comms command.

## Done when

Commands and thread actions are families from which every list, label and dispatch is derived; the probes and string comparisons are gone; the guards pass.

## Dispatch

> **`toad-t3`:** Complete T3 per `docs/refactor/T3-commands.md`. Read `00-RULES.md` first. Start after T2 merges. Build the `ThreadAction` family in its own module first, so T5 can adopt it in its widgets while you convert `app.py` and `Conversation`. Delete the dispatch functions outright once the families cover them.

## Implemented closure (PR120)

Slash commands implement core `Command.apply` directly. `CommandCatalog` is the
single derived ACP/local/contextual completion view; there is no `run` adapter,
maintained roster or name dispatch. Goal argument hints derive from GoalControl.
ThreadAction owns its ToolDeclaration and calls the existing domain service in
route admission; no second tool registry or result dictionary interpretation.
`ThreadContext`, `ChannelContext`, `FeedContext` and `ViewContext` own action and
pin behavior; `TargetContext.is_thread` is deleted. ChannelAction is a nominal
scope capability. Pointer and slash routes share declarations and ForkDialog.

The published paired T2 checkpoint08bc602 is integrated; typed goal/turn/
compaction/MCP facts and their consumers remain present. Compaction success is
its declared return or exception, with no result.get("ok") path. The two awaited
consumer handlers are async, matching shared MroDispatch's contract. All removed
command/probe/viewport helper callers are migrated; guards run in the shared
collector. Four class-growth findings are resolved; shared ratchet unchanged.

Current source and installed acceptance receipts: evidence/t3-sol/HANDOFF.md.
Parent owns merge and live activation, T2 owns remaining internal request/error
work, and T5 consumes the published nominal menu context contract. No live root,
route, launcher, conversion tool or independent error codec was changed by T3.
