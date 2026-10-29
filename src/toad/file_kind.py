"""Accepted attachment and preview kinds have one declaration owner."""
from pathlib import Path
from agent_comms.nominal.declared_family import DeclaredFamily
from textual.widgets import Static


class FileKind(DeclaredFamily, affix='FileKind'):
    suffixes = ()
    image = False
    mime_type = None

    @classmethod
    def for_path(cls, path: Path):
        return next((kind for kind in cls.members_with(cls) if path.suffix.lower() in kind.suffixes), GenericFileKind)

    MAX_BYTES = 1024 * 1024
    OVERSIZED_PREVIEW_BYTES = 64 * 1024

    @staticmethod
    def prepare_terminal():
        # The library owns detection; its queries must precede Textual's driver.
        import textual_image.widget  # noqa: F401

    @classmethod
    def load(cls, path):
        with path.open("rb") as source:
            return source.read(cls.MAX_BYTES + 1)

    @classmethod
    async def text(cls, view, data):
        if b"\0" in data:
            raise ValueError(f"{view.path.name} is a binary file.")
        if len(data) > cls.MAX_BYTES:
            data = data[:cls.OVERSIZED_PREVIEW_BYTES]
            await view.body.mount(Static("File exceeds 1 MiB; showing only the first 64 KiB."))
        return data.decode("utf-8", errors="replace")

    @classmethod
    async def show(cls, view, data):
        from toad.widgets.worker_static import WorkerStatic
        content = WorkerStatic.code(await cls.text(view, data), filename=str(view.path))
        await view.body.mount(content)
        await content.wait_ready()


    @classmethod
    async def show_at(cls, view, data, position):
        from toad.widgets.process_text_area import ProcessTextArea
        content = ProcessTextArea(soft_wrap=False, show_line_numbers=True)
        content.styles.height = "1fr"
        await view.body.mount(content)
        await content.load_text_prepared(await cls.text(view, data)).wait()
        position.reveal(content)


class GenericFileKind(FileKind):
    pass


class ImageFileKind(FileKind):
    image = True

    @classmethod
    def load(cls, path):
        from PIL import Image as PillowImage
        with PillowImage.open(path) as image:
            image.thumbnail((1600, 1600))
            return image.copy()

    @classmethod
    async def show(cls, view, image, position=None):
        from textual_image.widget import Image
        content = Image(image)
        content.styles.width = "auto"
        content.styles.height = "auto"
        await view.body.mount(content)

    # Images have no source cursor: both declared entry points use this behavior.
    show_at = show


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
    async def show(cls, view, data):
        from toad.widgets.line_markdown import LineMarkdown
        await view.body.mount(LineMarkdown(await cls.text(view, data)))
