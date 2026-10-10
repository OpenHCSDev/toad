#!/usr/bin/env bash
# The fixed scroll scenario for docs/performance/scroll-series.md.
# Usage: scroll_scenario.sh NAME [BIN_DIR]
# Forks perf-base-20261009 (a fork of Tristan's saved agent-comms-ux session), opens it
# with the real `toad` in st on the isolated display :121, and drives real X input:
# an active response, held PageUp from the input box, wheel bursts with reversal,
# End, and a return to the open tab. capture_live.py --frame-meter times every frame.
set -euo pipefail
name=$1
bin=${2:-$(dirname "$(readlink -f "$(command -v toad)")")}
tools=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
out=/home/ts/.cache/agent-scratch/scroll-series/$name
fork=perf-$name-$(date +%H%M%S)
project=/home/ts/wt/comms-post-feature-debt-audit-20260928
meter_seconds=${METER_SECONDS:-45}
export DISPLAY=${SCENARIO_DISPLAY:-:131}
rm -rf "$out"
mkdir -p "$out"

agent-comms fork --name "$fork" --parent perf-base-20261009 > "$out/fork.json"
env -u NO_COLOR -u TOAD_VALIDATION st -g145x50 -t "$fork" -e "$bin/toad" acp "$bin/agent-comms-acp" \
    --session "$fork" --project-dir "$project" --title "$fork" > "$out/st.log" 2>&1 &
st_pid=$!
cleanup() {
    xdotool key --window "$window" ctrl+q 2>/dev/null || true
    # Wait for the app to exit by itself: killing the terminal sends SIGHUP to
    # the app and its agents, and a process killed inside a guarded registry
    # write leaves the live bus's registry guard pending (fail-closed for all).
    for _ in $(seq 60); do kill -0 "$st_pid" 2>/dev/null || break; sleep 1; done
    if kill -0 "$st_pid" 2>/dev/null; then
        echo "app did not exit within 60 s; leaving it running rather than killing it mid-write" >&2
    fi
    # A fork is a full copy of the parent's 141 MB history: delete it, which
    # removes its registration, per-thread state and session files.
    agent-comms stop --name "$fork" > /dev/null 2>&1 || true
    agent-comms delete --name "$fork" > "$out/delete.json" 2>&1 || true
}
trap cleanup EXIT

for _ in $(seq 60); do
    app_pid=$(pgrep -P "$st_pid" | head -1 || true)
    window=$(xdotool search --pid "$st_pid" 2>/dev/null | head -1 || true)
    [[ -n "$app_pid" && -n "$window" ]] && break
    sleep 1
done
xdotool windowfocus --sync "$window"
# Optional: raise the UI thread's scheduling priority (for example UI_NICE=-10)
# to separate the app's own work from waiting for a CPU behind other processes.
if [[ -n "${UI_NICE:-}" ]]; then
    sudo -n renice -n "$UI_NICE" -p "$app_pid" > "$out/renice.log" 2>&1
fi
sleep "${LOAD_SECONDS:-25}"
read -r width height < <(xdotool getwindowgeometry --shell "$window" | sed -n 's/^\(WIDTH\|HEIGHT\)=//p' | paste -sd' ')
cell() { xdotool mousemove --window "$window" $(( ($1) * width / 145 + 3 )) $(( ($2) * height / 50 + height / 100 )) click 1; }
regions() { python3 "$tools/capture_live.py" --pid "$app_pid" --output-dir "$out" --name "$1" --targets --sudo > /dev/null; }
# Who asks the app to exit is written as it happens (the app has quit by
# itself when the second tab opened, with no error recorded).
python3 "$tools/capture_live.py" --pid "$app_pid" --output-dir "$out" --name app --trace-exit --sudo > /dev/null 2>&1 &
# Open a second tab from the sidebar so the scenario can return to this one.
cell 1 25
sleep 15
regions sidebar
# Prefer the usual idle thread; with many agents running it may be scrolled
# out of the sidebar, so take the first thread row on screen instead.
read -r row_x row_y < <(python3 -c "
import json,sys
rows=json.load(open(sys.argv[1]))['threads']
r=rows.get('parent-real-ui-20261009') or next(v for k, v in rows.items() if not k.startswith('perf-'))
print(r[0]+4, r[1])" "$out/sidebar-targets.json")
cell "$row_x" "$row_y"
for attempt in $(seq 15); do
    sleep 2
    regions "tabs-$attempt"
    tabs=$(python3 -c "import json,sys; print(len(json.load(open(sys.argv[1]))['tabs']))" "$out/tabs-$attempt-targets.json")
    [[ "$tabs" -ge 2 ]] && { cp "$out/tabs-$attempt-targets.json" "$out/tabs-targets.json"; break; }
done
if [[ "$tabs" -lt 2 ]]; then
    import -window "$window" "$out/tab-open-failed.png" 2>/dev/null || true
    echo "second tab did not open; see $out/tab-open-failed.png" >&2
    exit 1
fi
read -r first_x second_x tab_y < <(python3 -c "import json,sys; t=json.load(open(sys.argv[1]))['tabs']; print(t[0][0]+8, t[1][0]+8, t[0][1])" "$out/tabs-targets.json")
cell "$first_x" "$tab_y"
sleep 3
# Close the sidebar (its toggle sits on its right edge while open) and confirm.
for attempt in 1 2 3 4 5; do
    regions "closed-$attempt"
    open_rows=$(python3 -c "import json,sys; print(len(json.load(open(sys.argv[1]))['threads']))" "$out/closed-$attempt-targets.json")
    [[ "$open_rows" == 0 ]] && break
    cell 54 25
    sleep 5
done
[[ "$open_rows" == 0 ]] || { echo "sidebar did not close" >&2; exit 1; }
import -window "$window" "$out/loaded.png" 2>/dev/null || true
regions screen-loaded

if [[ -n "${PROFILE_SECONDS:-}" ]]; then
    measure=(--profile-seconds "$PROFILE_SECONDS" ${PROFILE_IDLE:+--idle} ${PROFILE_GIL:+--gil})
elif [[ -n "${PROFILE_LAYOUT:-}" ]]; then
    measure=(--profile-layout "$PROFILE_LAYOUT" ${PROFILE_TARGET:+--profile-target "$PROFILE_TARGET"}
             ${PROFILE_WITHIN:+--profile-within "$PROFILE_WITHIN"})
else
    measure=(--frame-meter "$meter_seconds")
fi
python3 "$tools/capture_live.py" --pid "$app_pid" --output-dir "$out" --name run \
    "${measure[@]}" ${TRACE_CALLS:+--trace-calls "$TRACE_CALLS"} ${TRACE_REFLOWS:+--trace-reflows} ${TRACE_RULES:+--trace-rules} --sudo > "$out/capture.log" 2>&1 &
capture=$!
sleep 2
# Optional load: a real channel message whose replies arrive during the scenario.
if [[ -n "${CHANNEL:-}" && -n "${CHANNEL_MESSAGE:-}" ]]; then
    "$HOME/.local/bin/agent-comms" user-send --to "$CHANNEL" --body "$CHANNEL_MESSAGE" --worktree "$project" > "$out/channel-send.json"
fi

# Active response: a real configured-provider turn that streams while we scroll.
cell 40 47
xdotool type --delay 5 "Explain in about 300 words why a terminal chat history should scroll prepared text instead of rebuilding widgets. No tools."
xdotool key Return
sleep 4
# Held PageUp from the input box: 30 key repeats per second for 3 seconds.
# Screen text is sampled during the hold, not only after it.
( sleep 0.8; regions screen-pageup-hold-1; sleep 0.6; regions screen-pageup-hold-2 ) &
holding=$!
xdotool key --repeat "${PAGEUP_REPEAT:-90}" --delay 33 Prior
wait "$holding"
import -window "$window" "$out/pageup.png" 2>/dev/null || true
regions screen-pageup
# Without input the reader's view holds still: loading earlier history above
# it must not move what is shown (checked by screen_checks.py).
sleep 2
regions screen-pageup-idle-1
sleep 2
regions screen-pageup-idle-2
# Wheel bursts with reversal over the history.
xdotool mousemove --window "$window" 400 300
for _ in 1 2 3; do
    xdotool click --repeat 25 --delay 10 4
    xdotool click --repeat 25 --delay 10 5
done
sleep 2
regions screen-wheel-idle-1
sleep 2
regions screen-wheel-idle-2
# End returns to the tail (End belongs to the history once it has focus).
xdotool click 1
xdotool key End
sleep 2
import -window "$window" "$out/end.png" 2>/dev/null || true
regions screen-end
# Tab return: switch to the other open tab and back.
cell "$second_x" "$tab_y"
sleep 2
cell "$first_x" "$tab_y"
sleep 1
import -window "$window" "$out/tab-return.png" 2>/dev/null || true
regions screen-tab-return

# A retired thread closes its open tab: delete this run's fork (cleanup
# would delete it anyway) and the observation service must close the tab.
# Archiving keeps the incarnation current, so it does not retire the view.
"$HOME/.local/bin/agent-comms" stop --name "$fork" > /dev/null 2>&1 || true
# Core refuses while any process still references the session (the agent
# exiting, a read in progress); retry as a person would, recording holders.
for attempt in 1 2 3 4 5; do
    "$HOME/.local/bin/agent-comms" delete --name "$fork" > "$out/delete-during-run.json" 2>&1 || true
    grep -q '"deleted"' "$out/delete-during-run.json" && break
    for pid in $(grep -o 'processes \[[0-9, ]*\]' "$out/delete-during-run.json" | grep -o '[0-9]\+'); do
        ps -o pid,ppid,args -p "$pid" >> "$out/delete-referrers.txt" 2>&1 || true
    done
    sleep 1
done
for attempt in $(seq 10); do
    sleep 1
    regions "retire-$attempt"
    tabs=$(python3 -c "import json,sys; print(len(json.load(open(sys.argv[1]))['tabs']))" "$out/retire-$attempt-targets.json")
    [[ "$tabs" -lt 2 ]] && break
done
echo "{\"tabs_after_delete\": $tabs}" > "$out/retire-check.json"

wait "$capture"
[[ -n "${PROFILE_SECONDS:-}${PROFILE_LAYOUT:-}" ]] || python3 "$tools/frame_meter.py" "$out/run-frames.json" | tee "$out/summary.json"
# What the reader saw, from the screen text: no placeholders or blank runs in
# the message window, End at the tail, tab return filled and still at the tail.
python3 "$tools/screen_checks.py" "$out" | tee "$out/screen-checks.json"

# Optional: the per-build layout figure for this live widget tree (after the
# checks, since it re-measures the screen at widths it is not shown at).
if [[ -n "${REMEASURE:-}" ]]; then
    python3 "$tools/capture_live.py" --pid "$app_pid" --output-dir "$out" --name remeasure \
        --remeasure "$REMEASURE" --sudo > /dev/null
    python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print({k: d[k] for k in ('median_ms', 'p10_ms', 'p90_ms')})" \
        "$out/remeasure-remeasure.json" | tee "$out/remeasure.txt"
fi

