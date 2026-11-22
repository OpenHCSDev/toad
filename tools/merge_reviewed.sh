#!/usr/bin/env bash
# Merge a reviewed toad PR only if the Qt inheritance ratchet, the shadow check and the APK's
# shipped-app check pass on that exact head.
#   tools/merge_reviewed.sh PR_NUMBER
# Fetches the PR head into a throwaway worktree, runs tools/qt_inherit_ratchet.py,
# tools/shadow_check.py and tools/android/check.sh there with the agent-comms runtime (it has
# PySide6 and Textual), and merges with --match-head-commit only when all exit 0.
# check.sh is build.sh's pre-buildozer half: a Qt import that reaches Textual code with an
# unshipped dependency fails here, not as a failed APK build after the merge (#2069).
# A head that moves after the check fails the merge instead of landing unchecked code.
# A head that does not contain current origin/main is refused: its renders and ratchet
# describe a tree that is not what main becomes, so the branch must rebase first.
# The head is read from the remote ref, not `gh pr view`: GitHub's API kept answering the
# pre-push head for a while after a force-push, and the gate refused rebased branches. A head
# that does not contain main is re-read for ~30 s before refusing, in case the ref is behind too.
# So is a head this checkout is ahead of: the push that just left it has not arrived.
set -euo pipefail
pr=${1:?usage: tools/merge_reviewed.sh PR_NUMBER}
runtime=$(ls -td "$HOME"/.local/share/agent-comms/runtimes/*/ | head -1)
toolchain=${TOAD_ANDROID_TOOLCHAIN:-$HOME/.cache/agent-scratch/android}
profile=${TOAD_ANDROID_PROFILE:-$HOME/.local/state/agent-comms/ui-profiles/pixel-8a.json}
# What would fail only after minutes of checks is refused before they start: a draft cannot
# merge, and the shipped-app check needs the toolchain's PySide6 wheel (a toolchain folder
# cleared from the scratch area failed inside assemble.py, 2026-11-21).
[ "$(gh pr view "$pr" --json isDraft -q .isDraft)" = false ] \
    || { echo "REFUSED: #$pr is a draft; mark it ready first (gh pr ready $pr)" >&2; exit 1; }
compgen -G "$toolchain/wheels/pyside6-*android_aarch64.whl" > /dev/null \
    || { echo "REFUSED: no Android toolchain at $toolchain; fill it with tools/android/toolchain.sh $toolchain" >&2; exit 1; }
check=$(mktemp -d)
trap 'git worktree remove --force "$check" >/dev/null 2>&1 || true' EXIT
here=$(git rev-parse HEAD)
for attempt in 1 2 3 4 5 6 7; do
    head=$(git ls-remote origin "refs/pull/$pr/head" | cut -f1)
    # This checkout is ahead of the PR's ref: a push made seconds ago has not reached it, and
    # checking now would check (and then refuse to merge) the commit before it.
    if [ -n "$head" ] && [ "$head" != "$here" ] && git merge-base --is-ancestor "$head" "$here" 2>/dev/null; then
        [ "$attempt" = 7 ] && { echo "REFUSED: #$pr head ${head:0:9} is behind this checkout's ${here:0:9}; push it, or run from the PR's head" >&2; exit 1; }
        sleep 5
        continue
    fi
    if [ -z "$head" ]; then
        # A PR opened seconds ago has no ref yet (#2163 was refused for this): read it again.
        [ "$attempt" = 7 ] && { echo "REFUSED: #$pr has no refs/pull/$pr/head on origin" >&2; exit 1; }
        sleep 5
        continue
    fi
    git fetch -q origin main "refs/pull/$pr/head"
    git merge-base --is-ancestor origin/main "$head" && break
    if [ "$attempt" = 7 ]; then
        echo "REFUSED: #$pr head ${head:0:9} does not contain origin/main $(git rev-parse --short origin/main); rebase it first" >&2
        exit 1
    fi
    sleep 5
done
git worktree add -q --detach "$check" "$head"
echo "ratchet on #$pr @ ${head:0:9}:"
( cd "$check" && QT_QPA_PLATFORM=offscreen PYTHONPATH=src "${runtime}bin/python" tools/qt_inherit_ratchet.py 2>&1 | grep -v propagateSizeHints )
echo "shadow check on #$pr @ ${head:0:9}:"
( cd "$check" && QT_QPA_PLATFORM=offscreen PYTHONPATH=src "${runtime}bin/python" tools/shadow_check.py 2>&1 | grep -v propagateSizeHints )
echo "type-only imports on #$pr @ ${head:0:9}:"
( cd "$check" && QT_QPA_PLATFORM=offscreen PYTHONPATH=src "${runtime}bin/python" tools/guarded_imports.py 2>&1 | grep -v propagateSizeHints )
echo "APK shipped-app check on #$pr @ ${head:0:9}:"
( cd "$check" && tools/android/check.sh "$runtime" "$toolchain" "$check/.apk-check" "$profile" 2>&1 \
    | grep -E '^(==|shipped app|a native crash|frame work|[[:space:]]+[0-9.]+ a frame|function-local|NEW|GONE|error:|Traceback|  File|[A-Za-z]+Error)' )
gh pr merge "$pr" --squash --admin --match-head-commit "$head"
gh pr view "$pr" --json state,mergeCommit -q '"#\(.number // "") \(.state) \(.mergeCommit.oid[0:9])"'
