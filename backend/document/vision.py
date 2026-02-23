"""Analyze images using OpenAI Vision API for OCR and content description."""

import base64
import io
import logging

from openai import AsyncOpenAI
from PIL import Image

logger = logging.getLogger(__name__)

# Map Pillow format names to MIME types
_FORMAT_TO_MIME = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "GIF": "image/gif",
    "WEBP": "image/webp",
    "BMP": "image/bmp",
    "TIFF": "image/tiff",
}

_SYSTEM_PROMPT = (
    "You are an image analysis assistant. Analyze the provided image and respond "
    "with two clearly labeled sections:\n\n"
    "## Extracted Text\n"
    "Transcribe ALL visible text in the image exactly as it appears — preserve "
    "formatting, line breaks, and structure. If there is no text, write "
    '"(No text detected)"\n\n'
    "## Image Description\n"
    "Describe the visual content of the image in detail: objects, people, layout, "
    "colors, charts, diagrams, or any other notable visual elements."
)


async def analyze_image(filename: str, content: bytes, api_key: str) -> str:
    """Analyze an image using OpenAI Vision API for OCR and description.

    Args:
        filename: Original filename (for logging).
        content: Raw image bytes.
        api_key: OpenAI API key.

    Returns:
        Combined OCR text and image description.

    Raises:
        ValueError: If the image is corrupt or in an unsupported format.
    """
    # Validate the image with Pillow
    try:
        img = Image.open(io.BytesIO(content))
        img.verify()  # Check for corruption
        # Re-open after verify (verify closes the image)
        img = Image.open(io.BytesIO(content))
        fmt = img.format
    except Exception as e:
        raise ValueError(f"Invalid or corrupt image file '{filename}': {e}")

    mime = _FORMAT_TO_MIME.get(fmt, "image/png")

    # Convert to base64 data URI
    b64 = base64.b64encode(content).decode("ascii")
    data_uri = f"data:{mime};base64,{b64}"

    logger.info(
        "Analyzing image '%s' (%s, %dx%d) via Vision API",
        filename,
        mime,
        img.width,
        img.height,
    )

    client = AsyncOpenAI(api_key=api_key)
    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"Analyze this image (filename: {filename}):",
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": data_uri, "detail": "high"},
                    },
                ],
            },
        ],
        max_tokens=4096,
    )

    result = response.choices[0].message.content or ""
    logger.info(
        "Vision API returned %d chars for '%s'",
        len(result),
        filename,
    )
    return result
