import base64
from pathlib import Path

from acp import schema
from acp.helpers import ContentBlock
from agent_comms.field_codec import FieldCodec
from agent_comms.image_inputs import ImageInput, prompt_images

from toad.clipboard_image import attachment_directory
from toad.file_kind import FileKind
from toad.prompt.extract import extract_paths_from_prompt
from toad.prompt.resource import ResourceError, load_resource


def build(project_path: Path, prompt: str) -> list[ContentBlock]:
    """Build the prompt structure and extract paths with the @ syntax.

    Args:
        project_path: The project root.
        prompt: The prompt text.

    Returns:
        A list of content blocks.
    """
    prompt_content: list[object] = []

    prompt_content.append({"type": "text", "text": prompt})
    image_spans = []
    for path, start, end in extract_paths_from_prompt(prompt):
        if path.endswith("/"):
            continue
        try:
            resource = load_resource(project_path, Path(path), attachment_root=attachment_directory())
        except ResourceError as error:
            if FileKind.for_path(Path(path)).image:
                raise ValueError(str(error)) from error
            # TODO: How should this be handled?
            continue
        uri = resource.path.resolve().as_uri()
        if resource.mime_type.startswith("image/") and resource.data is not None:
            image = ImageInput(base64.b64encode(resource.data).decode("ascii"), resource.mime_type)
            prompt_content.append({**FieldCodec.encode_record(image), "uri": uri})
            image_spans.append((start, end))
        elif resource.text is not None:
            prompt_content.append(
                {
                    "type": "resource",
                    "resource": {
                        "uri": uri,
                        "text": resource.text,
                        "mimeType": resource.mime_type,
                    },
                }
            )
        elif resource.data is not None:
            prompt_content.append(
                {
                    "type": "resource",
                    "resource": {
                        "uri": uri,
                        "blob": base64.b64encode(resource.data).decode("utf-8"),
                        "mimeType": resource.mime_type,
                    },
                }
            )

    # Attachment references remain in the composer/history (including queue
    # restoration), but aren't mistaken for @peer routing in the ACP text.
    for start, end in reversed(image_spans):
        prompt = prompt[:start] + prompt[end:]
    if image_spans:
        prompt_content[0]["text"] = prompt.strip()
    request = schema.PromptRequest.model_validate(
        {"sessionId": "attachments", "prompt": prompt_content}, strict=True
    )
    prompt_images(request)  # Validate the combined image count/size too.
    return request.prompt
