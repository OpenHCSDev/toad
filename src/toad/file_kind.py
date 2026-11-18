"""Accepted attachment and preview kinds have one declaration owner.

A kind says what a path is: its suffixes, whether it is an image and its mime type.
Every frontend and the agent prompt read these facts. How a frontend previews a kind is
that frontend's own family, keyed by these classes (Textual's is
`toad.widgets.file_viewer.FileViewer`), so this module imports no toolkit and no
preview library.
"""
from pathlib import Path

from agent_comms.nominal.declared_family import DeclaredFamily


class FileKind(DeclaredFamily, affix='FileKind'):
    suffixes = ()
    image = False
    mime_type = None

    @classmethod
    def for_path(cls, path: Path):
        return next((kind for kind in cls.members_with(cls) if path.suffix.lower() in kind.suffixes), GenericFileKind)


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
