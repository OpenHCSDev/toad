"""Real bounded files retain source text and recover complete seam records."""

import json
from pathlib import Path
import tempfile

from agent_comms.acp_failure import ProviderQuotaFailure
from toad.acp.log_records import (
    ErrorsLogView,
    EventsLogView,
    RawLogView,
    LogPage,
    FailureLogRecord,
    RecordFragment,
)
from toad.widgets.project_panel import FilePreview


def main():
    with tempfile.TemporaryDirectory(prefix="acp-records-") as directory:
        path = Path(directory) / "diagnostic.log"
        quota = (
            "[agent] "
            + json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "error": {
                        "code": -32603,
                        "message": "Internal error",
                        "data": {
                            "error": {"reason": {"details": "The usage limit has been reached (input not retried)"}}
                        },
                    },
                }
            )
            + "\n"
        )
        rpc = (
            "[client] "
            + repr({"jsonrpc": "2.0", "id": 7, "method": "session/prompt", "params": {"text": "界 café"}})
            + "\n"
        )
        # A complete error straddles the nominal latest-window boundary. Earlier
        # must recover it as one decoded record, never two unparseable fragments.
        budget = len(quota.encode()) + 24
        original = (
            rpc
            + quota
            + "backend stderr: failed to start\nTraceback (most recent call last):\n  ValueError: malformed reply\n"
        ).encode()
        path.write_bytes(original)
        pages = []
        before = None
        while True:
            page = LogPage.read(path, budget, before)
            assert len(page.raw) <= budget
            assert page.start < page.end
            pages.append(page)
            if page.start == 0:
                break
            before = page.start
        assert b"".join(page.raw for page in reversed(pages)) == original
        failures = [record for page in pages for record in page.records if isinstance(record, FailureLogRecord)]
        assert len(failures) == 1 and isinstance(failures[0].observation, ProviderQuotaFailure)
        assert quota == failures[0].raw
        whole = LogPage.read(path, FilePreview.MAX_BYTES)
        assert RawLogView().render(whole) == original.decode()
        assert "session/prompt" in EventsLogView().render(whole)
        errors = ErrorsLogView().render(whole)
        assert "usage limit has been reached" in errors
        assert "backend stderr: failed to start\nTraceback" in errors
        assert "ValueError: malformed reply" in errors
        # One oversized physical record remains a labeled fragment, without
        # silently claiming that its partial JSON is a parsed failure.
        path.write_bytes(b'[agent] {"result":"' + b"z" * (budget * 3) + b'"}\n')
        fragment = LogPage.read(path, budget)
        assert len(fragment.raw) == budget and isinstance(fragment.records[0], RecordFragment)
        assert "continues" in EventsLogView().render(fragment)
        # Sparse850MiB input proves bounded pages without allocating a huge log.
        with path.open("wb") as stream:
            stream.seek(850 * 1024 * 1024)
            stream.write(b"\n" + quota.encode())
        page = LogPage.read(path, FilePreview.MAX_BYTES)
        assert page.total > 850 * 1024 * 1024
        assert len(page.raw) <= FilePreview.MAX_BYTES
        assert "usage limit has been reached" in ErrorsLogView().render(page)
        print(
            json.dumps(
                {
                    "bounded_large_log": True,
                    "raw_exact": True,
                    "cross_window_failure_recovered": True,
                    "stderr_preserved": True,
                    "shared_quota_owner": True,
                    "page_budget": FilePreview.MAX_BYTES,
                }
            )
        )


if __name__ == "__main__":
    main()
