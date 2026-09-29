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
        app=InstalledApp(project_dir=str(root))
        async with app.run_test(size=(120,40)) as pilot:
            first=app.selected_session
            page=TranscriptPage(tuple(AssistantTranscript(f"BODY_RECORD_{i}\n\n"+"persistent paragraph "*60) for i in range(4)), TranscriptCursor("saved-body",0), TranscriptCursor("saved-body",4),False,False)
            async def publish():
                view=app.selected_session.conversation
                await view.contents.mount(TranscriptHistory(page))
                await settled(pilot,view)
                print("BODY_GEOMETRY",[(type(n).__name__,n.size,n.virtual_size,n.styles.height,n.styles.display) for n in view.window.walk_children()], "PAINT",conversation_paint(app.screen), flush=True)
                return view
            view=await publish()
            original=tuple(view.query(TranscriptFragmentView))
            assert "BODY_RECORD_3" in conversation_paint(app.screen)
            await app.new_session_screen(app.get_main_screen)
            await app.select_session(first.id)
            view=await publish()
            assert any(node is old for node in view.query(TranscriptFragmentView) for old in original)
            if "BODY_RECORD_3" not in conversation_paint(app.screen):
                before=conversation_paint(app.screen)
                view.contents.parent.refresh(layout=True)
                await settled(pilot,view)
                print("LAYOUT_INVALIDATION_DIAGNOSTIC", "BODY_RECORD_3" in conversation_paint(app.screen),
                      "before",before,"after",conversation_paint(app.screen),flush=True)
                raise AssertionError("Ordinary return lacked paint before explicit layout diagnostic")
            assert app._exception is None
    print("RETAINED_BODY_NATIVE_REPARENT_PAINT_EXIT_PASS",flush=True)

if __name__=="__main__": asyncio.run(main())
