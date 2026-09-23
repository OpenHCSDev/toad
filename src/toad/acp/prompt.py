import base64
from pathlib import Path

from toad.acp import protocol
from toad.prompt.extract import extract_paths_from_prompt
from toad.prompt.resource import load_resource, ResourceError
from toad.clipboard_image import attachment_directory
from agent_comms.image_inputs import ImageInput, prompt_images


def build(project_path: Path, prompt: str) -> list[protocol.ContentBlock]:
    """Build the prompt structure and extract paths with the @ syntax.

    Args:
        project_path: The project root.
        prompt: The prompt text.

    Returns:
        A list of content blocks.
    """
    prompt_content: list[protocol.ContentBlock] = []

    prompt_content.append({"type": "text", "text": prompt})
    image_spans = []
    for path, start, end in extract_paths_from_prompt(prompt):
        if path.endswith("/"):
            continue
        try:
            resource = load_resource(project_path, Path(path), attachment_root=attachment_directory())
        except ResourceError as error:
            if Path(path).suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
                raise ValueError(str(error)) from error
            # TODO: How should this be handled?
            continue
        uri = resource.path.resolve().as_uri()
        if resource.mime_type.startswith("image/") and resource.data is not None:
            image = ImageInput(base64.b64encode(resource.data).decode("ascii"), resource.mime_type)
            prompt_content.append({**image.to_rpc(), "uri": uri})
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
    prompt_images(prompt_content)  # Validate the combined image count/size too.
    return prompt_content
