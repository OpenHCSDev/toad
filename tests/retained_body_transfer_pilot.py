"""Installed workspace fragment custody uses native mount/reparent and painted strips."""
import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from agent_comms.transcripts import TranscriptCursor, TranscriptPage
from agent_comms.transcript_events import AssistantTranscript
from runtime_fixture import ToadApp
from native_session_retention_pilot import InstalledApp, conversation_paint
from viewport_recent_tabs_pilot import settled
from toad.widgets.transcript_history import TranscriptHistory, TranscriptFragmentView

async def main():
    with TemporaryDirectory(dir=os.environ["TMPDIR"], prefix="body-transfer-") as directory:
        root=Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root/"wire"), XDG_CONFIG_HOME=str(root/"config"), XDG_STATE_HOME=str(root/"state"), XDG_DATA_HOME=str(root/"data"))
        project=root/"project"
        project.mkdir()
        app=InstalledApp(project_dir=str(project))
        async with app.run_test(size=(120,40)) as pilot:
            first=app.selected_session
            repeated = AssistantTranscript("REPEATED_BODY_RECORD\n\n"+"persistent paragraph "*10)
            page=TranscriptPage((
                AssistantTranscript("BODY_RECORD_0\n\n"+"persistent paragraph "*10),
                repeated, repeated,
                AssistantTranscript("BODY_RECORD_3\n\n"+"persistent paragraph "*10),
            ), TranscriptCursor("saved-body",0), TranscriptCursor("saved-body",4),False,False)
            async def publish():
                view=app.selected_session.conversation
                history=TranscriptHistory(page)
                await view.contents.mount(history)
                await history.admit_retained_pages()
                await settled(pilot,view)
                print("BODY_GEOMETRY",[(type(n).__name__,n.size,n.virtual_size,n.styles.height,n.styles.display) for n in view.window.walk_children()], "PAINT",conversation_paint(app.screen), flush=True)
                return view
            view=await publish()
            original=tuple(view.query(TranscriptFragmentView))
            original_page=next(iter(view.window.histories)).pages[0]
            assert len(original) == 4 and original[1].fragment == original[2].fragment
            assert original[1].identity != original[2].identity
            assert all(body.body_ready for body in original)
            assert "BODY_RECORD_3" in conversation_paint(app.screen)
            await app.session_navigation.new(app.session_navigation.default_source)
            await app.select_session(first.id)
            view=await publish()
            assert next(iter(view.window.histories)).pages[0] is original_page
            returned=tuple(view.query(TranscriptFragmentView))
            assert len(returned) == len(original)
            assert returned[1] is original[1] and returned[2] is original[2], (
                "Identical saved events must reclaim their own positioned bodies",
                view.window.document_viewport.reuse_hits,
            )
            assert any(node is old for node in returned for old in original)
            if "BODY_RECORD_3" not in conversation_paint(app.screen):
                before=conversation_paint(app.screen)
                view.contents.parent.refresh(layout=True)
                await settled(pilot,view)
                print("LAYOUT_INVALIDATION_DIAGNOSTIC", "BODY_RECORD_3" in conversation_paint(app.screen),
                      "before",before,"after",conversation_paint(app.screen),flush=True)
                raise AssertionError("Ordinary return lacked paint before explicit layout diagnostic")
            assert app._exception is None
            # A changed saved page must use the existing fragment admission
            # path: unchanged bodies survive, but a rewritten row cannot paint.
            page=TranscriptPage((
                *page.events[:3], AssistantTranscript("BODY_RECORD_3_CHANGED"),
            ), page.before, page.after, False, False)
            await app.session_navigation.new(app.session_navigation.default_source)
            await app.select_session(first.id)
            view=await publish()
            changed=tuple(view.query(TranscriptFragmentView))
            assert next(iter(view.window.histories)).pages[0] is not original_page
            assert all(new is old for new, old in zip(changed[:3], original[:3]))
            assert changed[3] is not original[3]
            assert "BODY_RECORD_3_CHANGED" in conversation_paint(app.screen)
            assert app._exception is None
    print("RETAINED_BODY_NATIVE_REPARENT_PAINT_EXIT_PASS",flush=True)

if __name__=="__main__": asyncio.run(main())
