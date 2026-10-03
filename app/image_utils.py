import base64
import io

from fastapi import UploadFile
from PIL import Image, ImageOps

from .config import get_settings


async def process_image(
    file: UploadFile, max_size=(768, 768), attachment_size=(1600, 1600)
):
    """
    Process an uploaded image by resizing it to the specified dimensions and compressing it.

    Args:
        file: The uploaded file
        max_size: Maximum dimensions (width, height) for the resized image
        attachment_size: Maximum dimensions for the JPEG attached to the transaction

    Returns:
        A tuple containing (base64-encoded LLM JPEG, attachment JPEG bytes)
    """
    # Read the uploaded file
    contents = await file.read()

    # Open the image using PIL
    img = Image.open(io.BytesIO(contents))

    # Apply EXIF orientation (phone photos), since re-encoding drops EXIF
    img = ImageOps.exif_transpose(img)

    # Convert to RGB if necessary (in case of RGBA or other formats)
    if img.mode != "RGB":
        img = img.convert("RGB")

    # Attachment-sized JPEG for Firefly III
    attachment = img.copy()
    attachment.thumbnail(attachment_size, Image.LANCZOS)
    buffer = io.BytesIO()
    attachment.save(buffer, format="JPEG", quality=85)

    # Resize the image while maintaining aspect ratio
    img.thumbnail(max_size, Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=get_settings().image_quality)
    return base64.b64encode(buf.getvalue()).decode(), buffer.getvalue()
