"""Native read-only document navigation, prepared by the App's process renderer."""
from textual.widgets import PreparedTextArea
from toad.render_tasks import ReadOnlyDocumentRenderTask


class ProcessTextArea(PreparedTextArea):
    async def _prepare_document(self, source, width, tab_width):
        return await self.app.render_processes.submit(
            ReadOnlyDocumentRenderTask(source, width, tab_width))
