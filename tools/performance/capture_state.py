"""Read-only DTO capture of an authorized live Toad; no owner RPCs or UI input."""

def capture(*, expected_pid, output_prefix):
    import asyncio
    from collections import Counter
    from dataclasses import asdict
    import json
    import os
    import pickle
    import sys
    import threading
    import time
    import traceback
    from textual._context import active_app

    prefix = str(output_prefix)
    started = time.monotonic_ns()

    def write_json(path, data):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as output:
            json.dump(data, output, indent=2, default=str)

    try:
        if os.getpid() != expected_pid:
            raise RuntimeError("Unexpected capture process")
        app = active_app.get(None)
        if app is None:
            for task in asyncio.all_tasks():
                app = task.get_context().get(active_app, None)
                if app is not None:
                    break
        if app is None:
            raise RuntimeError("No application context")
        namespace = vars(app)
        stacks = tuple((name, tuple(stack)) for name, stack in app._screen_stacks.items())
        payload = {"schema": 1, "views": [], "sidebar_snapshot": namespace.get("_sidebar_snapshot")}
        metadata = {"schema": 1, "pid": os.getpid(), "captured_ns": time.time_ns(), "python": sys.version,
                    "current_mode": app.current_mode, "open_tab_order": list(app._open_tab_order),
                    "source_modules": {name: getattr(sys.modules.get(name), "__file__", None)
                                       for name in ("toad", "textual", "agent_comms")},
                    "registry_size": len(app._registry), "views": [], "truncated": False,
                    "capture_scope": "view state, loaded pages/live block sources, cached sidebar DTO; not process memory"}
        tracker = namespace.get("_session_tracker")
        payload["session_details"] = {mode: asdict(details) for mode, details in tracker.sessions.items()} if tracker is not None else {}
        for name in ("sidebar_state", "sidebar_layout"):
            model = namespace.get(name)
            if model is not None:
                payload[name] = dict(model.placements) if name == "sidebar_layout" else asdict(model)
        metadata["theme"] = namespace.get("_reactive_theme")
        try:
            metadata["size"] = tuple(app.size)
        except Exception:
            metadata["size"] = None
        total_nodes = 0
        closed_watch_paths = Counter()
        widget_classes = Counter()
        for mode, stack in stacks:
            for screen in stack:
                fields = vars(screen)
                view = {"mode": mode, "screen_class": type(screen).__name__,
                        "identity": {key: fields.get(key) for key in (
                            "_coordination_root", "_comms_thread", "_agent_session_id", "_agent_session_title",
                            "owner_mode", "me", "target", "kind", "recovery_root", "_reactive_project_path")},
                        "history_pages": [], "history_windows": [], "drafts": [], "live_blocks": [], "bars": [], "contents": []}
                if fields.get("_thread_sidebar_state") is not None:
                    view["thread_sidebar_state"] = asdict(fields["_thread_sidebar_state"])
                pending = [screen]
                while pending:
                    node = pending.pop()
                    total_nodes += 1
                    if total_nodes > 50000:
                        metadata["truncated"] = True
                        pending.clear()
                        break
                    data = vars(node)
                    kind = type(node).__name__
                    widget_classes[kind] += 1
                    children = data.get("_nodes")
                    if children is not None:
                        pending.extend(tuple(children._nodes))
                    for attribute, watchers in data.get("__watchers", {}).items():
                        for subscriber, callback in tuple(watchers):
                            if subscriber._closed:
                                closed_watch_paths[(kind, attribute, type(subscriber).__name__)] += 1
                    if kind == "Conversation":
                        view["visible_categories"] = tuple(data.get("_reactive_visible_categories", ()))
                        view["goal"] = data.get("_reactive_goal")
                        view["goal_execution"] = data.get("_reactive_goal_execution")
                    if kind in {"PromptTextArea", "ChannelTextArea"}:
                        document = data.get("document")
                        lines = vars(document).get("_lines") if document is not None else None
                        selection = data.get("_reactive_selection")
                        view["drafts"].append({"lines": tuple(lines) if lines is not None else None,
                                               "selection": tuple(tuple(point) for point in selection) if selection is not None else None})
                    if kind == "Contents" and type(node).__module__ == "toad.widgets.conversation":
                        for child in tuple(children._nodes) if children is not None else ():
                            child_data = vars(child)
                            child_kind = type(child).__name__
                            record = {"kind": child_kind, "id": child_data.get("_id")}
                            if child_kind == "TranscriptHistory":
                                record["pages"] = tuple((page.page, page.start, page.stop) for page in tuple(child_data.get("pages", ())))
                            elif child_kind == "ToolCall":
                                record["tool_call"] = dict(child_data.get("_reactive_tool_call") or {})
                                record["expanded"] = child_data.get("_reactive_expanded", False)
                            else:
                                record["text"] = next((child_data[key] for key in ("_markdown", "content", "source", "text", "_text", "_source")
                                                       if isinstance(child_data.get(key), str)), None)
                                for key in ("sender", "target", "route", "show_header", "show_divider", "sequence", "_message_category"):
                                    if key in child_data:
                                        record[key] = child_data[key]
                            view["contents"].append(record)
                    if kind == "TranscriptHistory":
                        view["history_pages"].append({
                            "through": data.get("through"),
                            "pages": tuple((page.page, page.start, page.stop) for page in tuple(data.get("pages", ()))),
                        })
                    if kind in {"Window", "HistoryWindow"}:
                        window = {key: data.get(key) for key in (
                            "_reactive_scroll_y", "_reactive_scroll_x", "_is_anchored", "_anchor_released")}
                        virtual_size = data.get("_reactive_virtual_size")
                        window["_reactive_virtual_size"] = tuple(virtual_size) if virtual_size is not None else None
                        view["history_windows"].append(window)
                    if data.get("_id") in {"channels-sidebar", "thread-sidebar"}:
                        view["bars"].append({"id": data["_id"], "collapsed": data.get("_reactive_collapsed"),
                                             "right": data.get("right")})
                    if kind == "CommsChatView":
                        # The second member is a mounted IRCMessage widget,
                        # not DTO data. Export only the immutable wire message.
                        view["wire_history"] = tuple(message for message, _widget in tuple(data.get("_history", ())))
                    if kind in {"AgentResponse", "AgentThought", "UserInput", "IncomingMessage", "CoordinationContext"}:
                        text = next((data[key] for key in ("_markdown", "source", "text", "_text", "_source")
                                     if isinstance(data.get(key), str)), None)
                        if text is not None:
                            view["live_blocks"].append({"kind": kind, "text": text, "route": data.get("route"),
                                                        "parent_class": type(node.parent).__name__})
                payload["views"].append(view)
                metadata["views"].append({"mode": mode, "screen_class": view["screen_class"],
                                          "identity": view["identity"], "history_pagers": len(view["history_pages"]),
                                          "loaded_pages": sum(len(history["pages"]) for history in view["history_pages"]),
                                          "live_blocks": len(view["live_blocks"]), "drafts": len(view["drafts"]),
                                          "contents_kinds": dict(Counter(record["kind"] for record in view["contents"])),
                                          "visible_categories": view.get("visible_categories")})
        metadata["widget_classes"] = widget_classes.most_common()
        metadata["closed_reactive_watch_paths"] = [(list(path), count) for path, count in closed_watch_paths.most_common()]
        metadata["ui_capture_ms"] = (time.monotonic_ns()-started)/1e6
        payload["metadata"] = metadata

        def persist():
            try:
                write_json(prefix + "-metadata.json", metadata)
                fd = os.open(prefix + ".pickle", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as output:
                    pickle.dump(payload, output, protocol=5)
                metadata["payload_bytes"] = os.stat(prefix + ".pickle").st_size
                write_json(prefix + ".json", metadata)
            except Exception:
                write_json(prefix + "-error.json", {"error": traceback.format_exc()})

        threading.Thread(target=persist, name="toad-authorized-state-export", daemon=True).start()
    except Exception:
        write_json(prefix + "-error.json", {"error": traceback.format_exc()})
