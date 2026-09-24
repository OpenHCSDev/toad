"""Measure next-frame latency when activating already-mounted conversation tabs."""

import asyncio
import cProfile
from collections import Counter
from contextlib import nullcontext
import inspect
import os
import statistics
import tempfile
import time
from pathlib import Path
from dataclasses import dataclass
from unittest.mock import patch

from toad.app import ToadApp
from toad.widgets.agent_response import AgentResponse
from toad.widgets.tool_call import ToolCall


@dataclass
class SwitchSample:
    mode: str
    started: float
    painted: asyncio.Future[float]


class SwitchProbe(ToadApp):
    CSS_PATH = Path(__file__).resolve().parents[1] / "src/toad/toad.tcss"
    pending_switch: SwitchSample | None = None

    def _display(self, screen, renderable):
        pending = self.pending_switch
        if (pending is not None and renderable is not None and not self._batch_count
                and self.current_mode == pending.mode and screen is self.screen):
            pending.painted.set_result(time.perf_counter() - pending.started)
            self.pending_switch = None
        return super()._display(screen, renderable)


async def main():
    # Permit profiling Toad's tab/paint pipeline while the separately owned
    # coordination snapshot implementation is being changed. This mode does
    # not benchmark the normal sidebar's coordination polling work.
    skip_comms = os.environ.get("TOAD_BENCH_SKIP_COMMS") == "1"
    if skip_comms:
        from toad.widgets.comms_sidebar import CommsSidebar

        async def skip_snapshot(self, revision):
            return None

        CommsSidebar._read_snapshot = skip_snapshot
    with tempfile.TemporaryDirectory(prefix="toad-switch-latency-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        app = SwitchProbe(project_dir=str(root))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            if os.environ.get("TOAD_PREWARM_CSS"):
                from textual.widgets._markdown import (MarkdownParagraph, MarkdownList,
                    MarkdownListItem, MarkdownBullet, MarkdownH2, MarkdownFence)
                from toad.widgets.agent_thought import AgentThought
                from toad.widgets.tool_call import ToolCallHeader, ToolContent
                from toad.widgets.transcript_history import (TranscriptHistory,
                    TranscriptPageView, TranscriptFragmentView)

                for cls in (AgentResponse, AgentThought, ToolCall, ToolCallHeader, ToolContent,
                            TranscriptHistory, TranscriptPageView, TranscriptFragmentView,
                            MarkdownParagraph, MarkdownList, MarkdownListItem, MarkdownBullet,
                            MarkdownH2, MarkdownFence):
                    for read_from, css, tie_breaker, scope in cls._get_default_css(object.__new__(cls)):
                        app.stylesheet.add_source(css, read_from=read_from,
                            is_default_css=True, tie_breaker=tie_breaker, scope=scope)
                app.stylesheet.update_nodes(set(app.screen.walk_children(with_self=True)))
                await pilot.pause()
            modes = [app.current_mode]
            tab_count = max(2, int(os.environ.get("TOAD_BENCH_TABS", "2")))
            responses = int(os.environ.get("TOAD_BENCH_RESPONSES", "12"))
            tools = int(os.environ.get("TOAD_BENCH_TOOLS", "0"))
            paragraphs = int(os.environ.get("TOAD_BENCH_PARAGRAPHS", "12"))
            paragraph_words = int(os.environ.get("TOAD_BENCH_PARAGRAPH_WORDS", "2"))
            tool_lines = int(os.environ.get("TOAD_BENCH_TOOL_LINES", "24"))
            busy = os.environ.get("TOAD_BENCH_BUSY") == "1"
            response_body = "\n\n".join(
                f"Paragraph {line}: " + "working data " * paragraph_words
                for line in range(paragraphs)
            )
            tool_output = "\n".join(
                f"Output line {line}: " + "working data " * 8
                for line in range(tool_lines)
            )
            for _ in range(tab_count - 1):
                await app.new_session_screen(app.get_main_screen)
                modes.append(app.current_mode)
            for mode in modes:
                await app.switch_mode(mode)
                await app.screen.conversation.contents.mount(*[
                    AgentResponse(f"## Block {i}\n\n" + response_body)
                    for i in range(responses)
                ])
                if tools:
                    await app.screen.conversation.contents.mount(*[
                        ToolCall({"toolCallId": f"{mode}-tool-{index}",
                                  "title": f"Run verification {index}", "kind": "execute",
                                  "status": "completed",
                                  "content": [{"type": "content", "content": {"type": "text",
                                  "text": tool_output}}]})
                        for index in range(tools)
                    ])
                if busy:
                    app.screen.conversation.busy_count = 1
                    app.screen.conversation.turn = "agent"
                await pilot.pause()
            timings = []
            profile_path = os.environ.get("TOAD_SWITCH_PROFILE")
            profiler = cProfile.Profile() if profile_path else None
            layout_calls = Counter()
            navigation_states = []
            slow_samples = []
            sidebar_events = []
            switch_index = [-1]
            if os.environ.get("TOAD_SWITCH_LAYOUT_TRACE"):
                from toad.screens.session_view import SessionView

                original = SessionView._refresh_layout

                def counted(screen, *args, **kwargs):
                    caller = inspect.currentframe().f_back.f_code.co_name
                    layout_calls[(caller, screen.id, kwargs.get("scroll", False))] += 1
                    return original(screen, *args, **kwargs)

                original_navigation = SessionView.layout_navigation

                async def nav_counted(screen):
                    navigation_states.append((screen.id, screen._layout_required,
                                              screen._scroll_required, len(screen._layout_widgets)))
                    return await original_navigation(screen)

                layout_context = (patch.object(SessionView, "_refresh_layout", counted),
                                  patch.object(SessionView, "layout_navigation", nav_counted))
            else:
                layout_context = (nullcontext(), nullcontext())
            if os.environ.get("TOAD_SWITCH_SIDEBAR_TRACE"):
                from toad.widgets.comms_sidebar import CommsSidebar

                original_present = CommsSidebar._present_snapshot

                async def timed_present(sidebar, snapshot):
                    started = time.perf_counter()
                    changed = snapshot != sidebar._last_snapshot
                    try:
                        return await original_present(sidebar, snapshot)
                    finally:
                        sidebar_events.append({"index": switch_index[0],
                            "mode": sidebar.screen.id,
                            "operation": "present_snapshot",
                            "changed": changed,
                            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1)})

                sidebar_context = patch.object(CommsSidebar, "_present_snapshot", timed_present)
            else:
                sidebar_context = nullcontext()
            with layout_context[0], layout_context[1], sidebar_context:
                for index, mode in enumerate(modes * (8 if tab_count == 2 else 2)):
                    switch_index[0] = index
                    rules_before = id(app.stylesheet.rules_map)
                    sources_before = set(app.stylesheet.source)
                    if profiler is not None:
                        profiler.enable()
                    started = time.perf_counter()
                    painted = asyncio.get_running_loop().create_future()
                    app.pending_switch = SwitchSample(mode, started, painted)
                    await app.switch_mode(mode)
                    duration = await asyncio.wait_for(painted, 5)
                    timings.append(duration)
                    if duration > .05:
                        active = app.screen
                        slow_samples.append({"index": index, "mode": mode,
                            "latency_ms": round(duration * 1000, 1),
                            "css_rules_changed": id(app.stylesheet.rules_map) != rules_before,
                            "new_css_sources": [str(source) for source in app.stylesheet.source.keys() - sources_before],
                            "resume_styles_changed": getattr(active, "_resume_styles_changed", None),
                            "layout_required": active._layout_required})
                    if profiler is not None:
                        profiler.disable()
            measurements = sorted(timings[2:])
            print({"tabs": tab_count, "responses_per_tab": responses,
                   "paragraphs_per_response": paragraphs,
                   "paragraph_words": paragraph_words,
                   "tools_per_tab": tools, "tool_lines": tool_lines,
                   "history_bytes_per_tab": responses * (len(response_body) + 16)
                                            + tools * len(tool_output),
                   "simulated_busy": busy,
                   "comms_polling_skipped": skip_comms,
                   "widgets": sum(len(list(app.get_screen_stack(mode)[0].walk_children())) for mode in modes),
                   "median_switch_ms": statistics.median(measurements) * 1000,
                   "p95_switch_ms": measurements[int(.95 * (len(measurements) - 1))] * 1000,
                   "max_switch_ms": max(measurements) * 1000,
                   "navigation_states": navigation_states,
                   "slow_samples": slow_samples,
                   "sidebar_events": [event for event in sidebar_events
                                      if event["index"] in {sample["index"] for sample in slow_samples}
                                      or event["elapsed_ms"] > 30],
                   "layout_calls": [{"caller": key[0], "mode": key[1], "scroll": key[2], "count": count}
                                    for key, count in layout_calls.most_common()]})
            if profiler is not None:
                profiler.dump_stats(profile_path)
            if os.environ.get("TOAD_BENCH_ENFORCE_16") == "1":
                assert max(timings) < .016, f"Worst painted tab switch: {max(timings) * 1000:.1f} ms"
        await asyncio.get_running_loop().shutdown_default_executor()


if __name__ == "__main__":
    asyncio.run(main())
