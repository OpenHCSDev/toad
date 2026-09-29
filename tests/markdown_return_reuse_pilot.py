"""Installed painted body remount uses bounded syntax, with fresh file resolution.

This isolates the return preparation boundary without Node or a model provider.
The complete multiple-native-session return gate is run once the host upgrade ends.
"""
import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from runtime_fixture import ToadApp
from sidebar_retirement_pilot import until, viewport_text
from toad.render_tasks import MarkdownSyntaxRenderTask
from toad.work_preparation import RenderPreparation
from toad.widgets.agent_response import AgentResponse
from textual.widgets._markdown import MarkdownParagraph
from textual.style import Style


async def main():
    with TemporaryDirectory(dir=os.environ["TMPDIR"], prefix="syntax-return-") as directory:
        project = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(project / "wire"),
                          TOAD_TEST_ATTEMPT=f"syntax-return-{os.getpid()}",
                          XDG_CONFIG_HOME=str(project / "config"),
                          XDG_STATE_HOME=str(project / "state"),
                          XDG_DATA_HOME=str(project / "data"))
        app = ToadApp(project_dir=str(project))
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause()
            view = app.selected_session.conversation
            sources = [f"RETURN_SOURCE_{index} file-{index}.py\n\n" + "**retained syntax** " * 20
                       for index in range(2)]
            keys = [await RenderPreparation(MarkdownSyntaxRenderTask(source)).identity(app.preparation)
                    for source in sources]
            retained = {}
            mounted = []
            painted_ms = []
            for index in (0, 1, 0, 1, 0):
                before = app.preparation.hits
                started = perf_counter()
                response = AgentResponse(sources[index], paginate=False)
                await view.post(response)
                response.scroll_visible(animate=False, immediate=True)
                await until(pilot, lambda: response in app.screen._compositor.visible_widgets and
                            f"RETURN_SOURCE_{index}" in viewport_text(response))
                await until(pilot, lambda: bool(response.query(MarkdownParagraph)))
                painted_ms.append((perf_counter() - started) * 1000)
                paragraphs = list(response.query(MarkdownParagraph))
                mounted.append(len(paragraphs))
                links = [span.style.meta.get("@click", "") for paragraph in paragraphs
                         for span in paragraph._content.spans if isinstance(span.style, Style)]
                expected = "toad-file-search:" if index not in retained else "toad-file:"
                assert any(expected in action for action in links), links
                value = app.preparation._ready[keys[index]][0]
                if index in retained:
                    assert value is retained[index], "Return replaced retained syntax"
                    assert app.preparation.hits > before, "Body return did not reuse preparation"
                else:
                    retained[index] = value
                    (project / f"file-{index}.py").write_text("pass\n")
                assert app.preparation.retained_bytes <= app.preparation.max_bytes
                await response.remove()
                assert not view.query(AgentResponse), "Retired body remained pooled"
            assert app._exception is None
            print("INSTALLED_PAINTED_ABABA_SYNTAX_REUSE_FRESH_LINKS_NO_BODY_POOL", {
                "hits": app.preparation.hits, "misses": app.preparation.misses,
                "retained_bytes": app.preparation.retained_bytes,
                "budget": app.preparation.max_bytes, "mounted_paragraphs": mounted, "painted_ms": painted_ms,
            }, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
