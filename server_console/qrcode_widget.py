"""Local, offline QR code generation for the mobile URL (segno; no network call)."""

from __future__ import annotations

import io

import segno
from PIL import Image


def qr_image(text: str, *, faded: bool = False, scale: int = 8, border: int = 1) -> Image.Image:
    """PNG of `text` as a Pillow image; `faded` blends it to 20% over white
    (the spec's look while the server is not running)."""

    buffer = io.BytesIO()
    segno.make(text, error="m").save(
        buffer, kind="png", scale=scale, border=border, dark="#1C2024", light="#FFFFFF"
    )
    buffer.seek(0)
    picture = Image.open(buffer).convert("RGB")
    if faded:
        picture = Image.blend(Image.new("RGB", picture.size, "#FFFFFF"), picture, 0.2)
    return picture
