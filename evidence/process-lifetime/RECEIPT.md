# T4 ACP process lifetime closure

Base Toad main c2534676; persistent own tree toad-agent-process-lifetime-sol-20260928. Original archived T4 plan reread. Latest refactor-audit2216 and NRA reread; IMPL-13 and IDEN-8 applied: delete local ProcessControl/Posix/Windows signal/group retirement and maintenance cancellation supervisor; use core gated AttachedChild.start and identity-bound stop. IMPL-10: nominal active/closed disposition owns update admission and one connection-close transition. AgentProcess now owns launch environment/cwd/root selection, prompt admission/write, response task admission, session lifetime and guaranteed retirement through finally. Agent/controller/wire/coordination consumers migrated. No legacy aliases or process control fallback.

New platform case previously required spawn-options, finish, stop and cancellation cleanup in two files. Now core Platform owns OS custody/retirement; Toad ShellCommand only owns shell argv syntax. New cleanup behavior has one AgentProcess.retire path; EOF/stop/cancellation join it. Tesla source binding and Noether ACPPlan unchanged.

Exact installed noneditable Toad wheel with paired core runtime-native-custody-terminal-20260928 and Textualc974 dependencies. Parent owns new framework pins/install. No paid calls, live roots, replay, owner restart or CI wait.

* maintenance_boundary_pilot: actual child completes; closed ingress denies launch.
* maintenance_cancel_process_group_pilot: repeated cancellation while actual gated shell+descendant launch pending; descendants gone before gate release.
* default_route_retirement_pilot: actual old-root child/group retired before route publication, exit0.
* agent_process_retirement_installed_pilot: actual EOF/cancel/stop child+descendant and session task retirement, all3 pass.
* l0a_native_installed_pilot final: actual physical Pi/ACP loopback model; live+saved viewport text, checkpoint paint, queue consumption, cold reattach, DM/channel delivery, stopped-owner reopen, process cleanup; exit0. Initial native run also passed before moving final Agent start/send caller authority.
* T4 guards: initial overbroad kill guard falsely rejected existing terminal-controller kill; narrowed to process/admission owners, failed receipt retained. Final receipt guards.log.

Measurements attached per touched file. No boolean chain-term increases. Agent1311→1257; controller95→92; AgentProcess119→189 (takes actual launch/send/retirement authority); removed three control classes and duplicate maintenance cleanup. This is semantic consolidation, not class-size evidence alone. No global NRA clean claim. Windows shell declaration not exercised on this POSIX host.
