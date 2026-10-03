import base64
import io

import pytest
from fastapi import UploadFile
from PIL import Image

from app.image_utils import process_image
from tests.conftest import make_image


def upload(data: bytes) -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename="receipt.png")


async def test_resizes_preserving_aspect_ratio():
    llm_b64, attachment = await process_image(upload(make_image((3000, 1500))))

    llm_img = Image.open(io.BytesIO(base64.b64decode(llm_b64)))
    assert llm_img.format == "JPEG"
    assert llm_img.size == (768, 384)

    att_img = Image.open(io.BytesIO(attachment))
    assert att_img.format == "JPEG"
    assert att_img.size == (1600, 800)


async def test_small_image_not_upscaled():
    llm_b64, attachment = await process_image(upload(make_image((200, 100))))
    assert Image.open(io.BytesIO(base64.b64decode(llm_b64))).size == (200, 100)
    assert Image.open(io.BytesIO(attachment)).size == (200, 100)


@pytest.mark.parametrize("mode", ["RGBA", "L", "P"])
async def test_converts_to_rgb(mode):
    llm_b64, attachment = await process_image(upload(make_image(mode=mode)))
    assert Image.open(io.BytesIO(base64.b64decode(llm_b64))).mode == "RGB"
    assert Image.open(io.BytesIO(attachment)).mode == "RGB"


async def test_applies_exif_orientation():
    img = Image.new("RGB", (200, 100), "white")
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90° CW on display
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)

    llm_b64, _ = await process_image(upload(buf.getvalue()))
    assert Image.open(io.BytesIO(base64.b64decode(llm_b64))).size == (100, 200)


async def test_invalid_image_raises():
    with pytest.raises(Exception):
        await process_image(upload(b"not an image"))
