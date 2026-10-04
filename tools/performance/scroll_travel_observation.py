"""Local native event receipts for the #254 travel discriminator.

Only the recorder's owned UI is observed. No product methods are replaced.
The observed position, demand and expiry remain owned by DirectionalPreparation.
"""

import json
import os
from pathlib import Path
import sys
from time import monotonic_ns


class ScrollTravelObservation:
    def __init__(self, path):
        from textual.widgets import TextArea
        from toad.widgets.history_anchor import HistoryWindow
        from toad.widgets.presentation_window import DirectionalPreparation
        from toad.widgets.viewport_body import BodyMeasurement, DocumentViewport, MeasuredViewportBody
        from toad.widgets.transcript_history import TranscriptHistory
        from toad.sidebar_projection import SidebarProjection
        from toad.widgets.sidebar_viewport import SidebarViewport
        from textual.widget import Widget
        from textual._animator import Animator

        self.written = 0
        self.observer_ns = 0
        self.sidebar_viewport_type = SidebarViewport
        self.history_window_type = HistoryWindow
        self.starts = {
            DocumentViewport.request.__code__: self.request,
            HistoryWindow.watch_scroll_y.__code__: self.scroll,
            TextArea.action_cursor_page_up.__code__: self.editor_page_up,
            HistoryWindow.action_page_up.__code__: self.history_page_up,
            TextArea.action_cursor_page_down.__code__: self.editor_page_down,
            HistoryWindow.action_page_down.__code__: self.history_page_down,
            DirectionalPreparation.relocated.__code__: self.relocating,
            DocumentViewport.admission.__code__: self.full_admission,
            BodyMeasurement.start_materialization.__code__: self.materializing,
            MeasuredViewportBody.retire_native_body.__code__: self.retiring,
            TranscriptHistory._resource_fragment_budget.__code__: self.fragment_budget,
            TranscriptHistory._extend_and_trim.__code__: self.page_extension,
            SidebarProjection.rebuild.__code__: self.sidebar_publishing,
            Widget.watch_scroll_y.__code__: self.sidebar_scroll,
            Animator.force_stop_animation.__code__: self.animation_stopping,
            Animator.transform_running_animation.__code__: self.animation_transforming,
        }
        self.returns = {
            DirectionalPreparation.observe.__code__: self.observed,
            DirectionalPreparation.relocated.__code__: self.relocated,
            TranscriptHistory._extend_and_trim.__code__: self.page_extended,
            SidebarProjection.rebuild.__code__: self.sidebar_published,
            Animator.transform_running_animation.__code__: self.animation_transformed,
        }
        self.tool = sys.monitoring.PROFILER_ID
        self.stream = path.open("x", buffering=1)

    def emit(self, event, **values):
        self.written += 1
        self.stream.write(json.dumps(dict(monotonic_ns=monotonic_ns(), event=event,
            observer_ns_before=self.observer_ns, **values)) + "\n")
        if self.written == 20000:
            self.close()

    def request(self, native):
        window = native["self"].window
        caller = sys._getframe(2).f_back.f_code
        self.emit("request", window=id(window), position=window.scroll_y,
                  restoring=window._restoring,
                  caller=caller.co_name, caller_source=caller.co_filename)

    def body_transition(self, event, body):
        viewport = body._body_viewport
        self.emit(event, body=id(body), window=id(viewport.window) if viewport is not None else None,
                  state=type(body._body_measurement).__name__)

    def materializing(self, native):
        self.body_transition('body_materialization', native['body'])

    def retiring(self, native):
        self.body_transition('body_retirement_attempt', native['self'])

    def full_admission(self, native):
        caller = sys._getframe(2).f_back.f_code
        self.emit("full_admission", window=id(native["self"].window),
                  caller=caller.co_name, caller_source=caller.co_filename)

    def fragment_budget(self, native):
        self.emit("fragment_budget", history=id(native["self"]),
                  window=id(native["self"].window))

    def page_extension(self, native):
        self.emit("page_extension", history=id(native["self"]),
                  window=id(native["self"].window), local=native["local"],
                  older=native["older"])

    def page_extended(self, native):
        self.emit("page_extended", history=id(native["self"]),
                  window=id(native["self"].window), local=native["local"],
                  older=native["older"])

    def sidebar_scene(self, projection):
        sidebar = projection.sidebar
        if not sidebar.accepts_publication():
            return {"sidebar": id(sidebar), "publication_revoked": True}
        viewport, _ = sidebar.navigation.scroll_containers
        compositor = sidebar.screen._compositor
        mapping = (compositor._visible_map if compositor._visible_map is not None
                   else compositor._full_map)
        geometry = mapping.get(viewport)
        top = None
        if geometry is not None:
            bounds = geometry.region.intersection(geometry.clip)
            visible = []
            for row in projection.rows:
                position = mapping.get(row)
                if position is not None and position.region.intersection(position.clip).overlaps(bounds):
                    visible.append((position.region.y, id(row), row.target_name))
            if visible:
                y, identity, target = min(visible)
                top = {"object_id": identity, "target": target, "offset": y - bounds.y}
        return {"sidebar": id(sidebar), "viewport": id(viewport),
                "scroll_y": viewport.scroll_y, "top": top,
                "map_invalidated": compositor._full_map_invalidated}

    def sidebar_publishing(self, native):
        self.emit("sidebar_publication_start", **self.sidebar_scene(native["self"]))

    def sidebar_published(self, native):
        self.emit("sidebar_publication_done", **self.sidebar_scene(native["self"]))

    def sidebar_scroll(self, native):
        viewport = native["self"]
        if isinstance(viewport, self.sidebar_viewport_type):
            self.emit("sidebar_scroll", viewport=id(viewport),
                      old=native["old_value"], new=native["new_value"])

    def animation_event(self, event, native):
        window, attribute = native["obj"], native["attribute"]
        if not isinstance(window, self.history_window_type) or attribute not in ("scroll_x", "scroll_y"):
            return
        # These are the original numeric scroll animation's owned operands,
        # recorded only in the authorized diagnostic artifact, never retained
        # as product state or another animation registry.
        animation = native["self"]._animations.get((id(window), attribute))
        facts = {} if animation is None else {
            "identity": id(animation), "start_time": animation.start_time,
            "duration": animation.duration, "start": animation.start_value,
            "end": animation.end_value, "final": animation.final_value,
        }
        caller = sys._getframe(3).f_back.f_code
        self.emit(event, window=id(window), attribute=attribute, animation=facts,
                  caller=caller.co_name, caller_source=caller.co_filename)

    def animation_stopping(self, native):
        self.animation_event("animation_stopping", native)

    def animation_transforming(self, native):
        self.animation_event("animation_transforming", native)

    def animation_transformed(self, native):
        self.animation_event("animation_transformed", native)

    def scroll(self, native):
        window = native["self"]
        self.emit("scroll", window=id(window), old=native["old_value"],
                  new=native["new_value"], restoring=window._restoring)

    def editor_page_up(self, native):
        self.emit("editor_page_up", editor=id(native["self"]))

    def history_page_up(self, native):
        self.emit("history_page_up", window=id(native["self"]))

    def editor_page_down(self, native):
        self.emit("editor_page_down", editor=id(native["self"]))

    def history_page_down(self, native):
        self.emit("history_page_down", window=id(native["self"]))

    def observed(self, native):
        lookahead = native["self"]
        self.emit("observe", window=id(lookahead.viewport.window),
                  position=native["position"], travel=native["travel"],
                  tracked_position=lookahead.position, sampled_at=lookahead.sampled_at,
                  predicted_rows=lookahead.travel_rows,
                  demand=type(lookahead.demand).__name__)

    def relocated(self, native):
        lookahead = native["self"]
        self.emit("relocated", window=id(lookahead.viewport.window),
                  compensation=native["compensation"], tracked_position=lookahead.position,
                  sampled_at=lookahead.sampled_at, predicted_rows=lookahead.travel_rows,
                  demand=type(lookahead.demand).__name__)

    def relocating(self, native):
        lookahead = native["self"]
        self.emit("relocating", window=id(lookahead.viewport.window),
                  compensation=native["compensation"], tracked_position=lookahead.position,
                  sampled_at=lookahead.sampled_at)

    def start(self, code, offset):
        started = monotonic_ns()
        self.starts[code](sys._getframe(1).f_locals)
        self.observer_ns += monotonic_ns() - started

    def returned(self, code, offset, value):
        started = monotonic_ns()
        self.returns[code](sys._getframe(1).f_locals)
        self.observer_ns += monotonic_ns() - started

    def install(self):
        sys.monitoring.use_tool_id(self.tool, "toad-recorder-scroll-travel")
        sys.monitoring.register_callback(self.tool, sys.monitoring.events.PY_START, self.start)
        sys.monitoring.register_callback(self.tool, sys.monitoring.events.PY_RETURN, self.returned)
        for code in self.starts.keys() | self.returns.keys():
            events = (sys.monitoring.events.PY_START if code in self.starts else 0)
            events |= (sys.monitoring.events.PY_RETURN if code in self.returns else 0)
            sys.monitoring.set_local_events(self.tool, code, events)
        self.emit("installed", pid=os.getpid(),
                  sources=sorted({code.co_filename for code in (*self.starts, *self.returns)}))

    def close(self):
        for code in (*self.starts, *self.returns):
            sys.monitoring.set_local_events(self.tool, code, 0)
        sys.monitoring.register_callback(self.tool, sys.monitoring.events.PY_START, None)
        sys.monitoring.register_callback(self.tool, sys.monitoring.events.PY_RETURN, None)
        sys.monitoring.free_tool_id(self.tool)
        self.stream.close()


def install(*, expected_pid, output):
    if os.getpid() != expected_pid:
        raise RuntimeError("Scroll observation process identity changed")
    path = Path(output).resolve()
    if not path.is_relative_to((Path.home() / ".cache/agent-scratch").resolve()):
        raise ValueError("Scroll trace requires recorder-owned persistent scratch")
    if sys.monitoring.get_tool(sys.monitoring.PROFILER_ID) is not None:
        raise RuntimeError("The native monitoring slot already has an owner")
    observation = ScrollTravelObservation(path)
    observation.install()
    return observation
