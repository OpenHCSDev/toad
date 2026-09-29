"""Accepted attachment and preview kinds have one declaration owner."""
from pathlib import Path
from agent_comms.declared_family import DeclaredFamily


class FileKind(DeclaredFamily, affix='FileKind'):
    suffixes = ()
    image = False
    mime_type = None

    @classmethod
    def for_path(cls, path: Path):
        return next((kind for kind in cls.members_with(cls) if path.suffix.lower() in kind.suffixes), GenericFileKind)

    @classmethod
    async def preview(cls, view, text):
        from toad.widgets.worker_static import WorkerStatic
        content = WorkerStatic.code(text, filename=str(view.path))
        await view.mount(content)
        await content.wait_ready()


class GenericFileKind(FileKind):
    pass


class ImageFileKind(FileKind):
    image = True


class PngFileKind(ImageFileKind):
    suffixes = ('.png',)
    mime_type = 'image/png'


class JpegFileKind(ImageFileKind):
    suffixes = ('.jpg', '.jpeg')
    mime_type = 'image/jpeg'


class GifFileKind(ImageFileKind):
    suffixes = ('.gif',)
    mime_type = 'image/gif'


class WebpFileKind(ImageFileKind):
    suffixes = ('.webp',)
    mime_type = 'image/webp'


class MarkdownFileKind(FileKind):
    suffixes = ('.md', '.markdown', '.mdown')
    mime_type = 'text/markdown'

    @classmethod
    async def preview(cls, view, text):
        from toad.widgets.prepared_markdown import PreparedConversationMarkdown
        content = PreparedConversationMarkdown()
        await view.mount(content)
        await content.update(text)
