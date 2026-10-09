# Shutdown stack custody across awaited destruction

Authentic user terminal trace retained exactly: old runtime-native-custody-terminal App.run->_shutdown->_close_all iterates _screen_stacks.values; RuntimeError dictionary changed size during iteration. Separate fromIndexErrorPR9, no delay/hold toPR9.

Actual installed oldc974 reprod: real139x40to139x25 resize and first/secondary/first mode return; a real widget on_unmount removes inactive secondary mode while shutdown awaits _prune. No dictionary mocking/direct mutation; actual remove_mode boundary. Captured exact same _close_all RuntimeError. First harness mistakenly used unregistered _default in an App declaring only secondary, causing UnknownMode/ActiveMode errors; corrected explicit first/secondary modes; failed receipt retained.

Fix takes tuple of admitted screen-stack references before first shutdown await. Mode removal remains allowed, already-retired screens use existing _running lifecycle gate, stack.clear and existing remaining-node cleanup still execute. No dictionary exception catch, silent skip, preservation of destroyed state, alternate screen store/lifecycle or teardown retry. Shutdown owns admitted worklist; live mode dictionary owns membership. Single existing owner, IDEN-1 snapshot and IMPL-10 destruction lifetime; AGENT-8 real installed tests. Latest2216 skill applies. No class-size/chain increase, no changed wire.

Installed corrected native resize/mode/unmount gate passes: exactly both content/secondary destruction callbacks, registry empty, installed screens/modes empty, every retained stack empty. Ordinary App, not a fake shutdown method. First actual PTY old-compositor-dependent crash recipe timed out before marker, owned child explicitly stopped; retained honestly, not a pass. Permanent crash test uses controlled UI IndexError after actual resize and switch/return so PR9 can fix original compositor independently.

Parent owns merge/install. No owner restart, live data, provider prompts, paid calls or CI wait. Tesla142 frameworkApp._close_all minimal scope coordinated142comment5883105046. Own persistent~/wt/textual-shutdown-mode-custody-sol-20260928.

Final branch consumes mergedPR9mainb1efffff. Actual installed PTY controlledUIIndexError after real resize/mode-return PASS: original retained UI error preserved, both destructors execute, empty registry/screens/modes/stacks, no shutdown dictionary RuntimeError. No IndexError-root workaround reintroduced. Final focused shutdown+existingmode cases recorded in focused-final.txt; UI-only fix, no provider run needed.

Focused final gate11 PASS2.66s. First pytest collection failed from unqualified sibling import in packaged tests; corrected tests.shutdown_mode_installed_pilot import and retained failure. App ASTspan4755→4755/chainterms4→4. No unchanged broad rerun.
