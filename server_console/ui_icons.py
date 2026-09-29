"""Line icons drawn with Pillow (no image files to ship or lose)."""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageTk

from server_console.ui_theme import px, scale

_SUPERSAMPLE = 6
_cache: dict[tuple, ImageTk.PhotoImage] = {}


def _canvas(size: int):
    px = size * _SUPERSAMPLE
    image = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    return image, ImageDraw.Draw(image), px


def _stroke(size: float) -> int:
    return max(2, round(size * 0.115 * _SUPERSAMPLE))


def _draw(name: str, size: int, color: str) -> Image.Image:
    image, draw, px = _canvas(size)
    width = _stroke(size)
    u = px / 24  # every icon is designed on a 24-unit grid
    if name == "play":
        draw.polygon([(7 * u, 4.5 * u), (19 * u, 12 * u), (7 * u, 19.5 * u)], outline=color, width=width)
    elif name == "stop":
        draw.rounded_rectangle((5 * u, 5 * u, 19 * u, 19 * u), radius=2.5 * u, outline=color, width=width)
    elif name == "restart":
        box = (4.5 * u, 4.5 * u, 19.5 * u, 19.5 * u)
        draw.arc(box, start=-40, end=250, fill=color, width=width)
        tip = (19.6 * u, 6.2 * u)
        draw.polygon([tip, (14.6 * u, 5.6 * u), (18.9 * u, 10.4 * u)], fill=color)
    elif name == "backup":
        draw.rounded_rectangle((4 * u, 14 * u, 20 * u, 20 * u), radius=2 * u, outline=color, width=width)
        draw.line((12 * u, 4 * u, 12 * u, 14 * u), fill=color, width=width)
        draw.line((8 * u, 10 * u, 12 * u, 14 * u, 16 * u, 10 * u), fill=color, width=width, joint="curve")
    elif name == "folder":
        draw.line(
            (3.5 * u, 7 * u, 3.5 * u, 19 * u, 20.5 * u, 19 * u, 20.5 * u, 8.5 * u,
             11 * u, 8.5 * u, 9 * u, 5.5 * u, 3.5 * u, 5.5 * u, 3.5 * u, 7 * u),
            fill=color, width=width, joint="curve",
        )
    elif name == "phone":
        draw.rounded_rectangle((7 * u, 3 * u, 17 * u, 21 * u), radius=2.5 * u, outline=color, width=width)
        draw.line((10.5 * u, 17.5 * u, 13.5 * u, 17.5 * u), fill=color, width=width)
    elif name == "copy":
        draw.rounded_rectangle((8.5 * u, 8.5 * u, 20 * u, 20 * u), radius=2 * u, outline=color, width=width)
        draw.line((15.5 * u, 4 * u, 6 * u, 4 * u, 4 * u, 6 * u, 4 * u, 15.5 * u), fill=color, width=width, joint="curve")
    elif name == "server":
        draw.rounded_rectangle((3 * u, 3.5 * u, 21 * u, 10.5 * u), radius=2 * u, outline=color, width=width)
        draw.rounded_rectangle((3 * u, 13.5 * u, 21 * u, 20.5 * u), radius=2 * u, outline=color, width=width)
        for y in (7 * u, 17 * u):
            draw.ellipse((6 * u - width / 2, y - width / 2, 6 * u + width / 2, y + width / 2), fill=color)
    else:  # pragma: no cover - programming error
        raise ValueError(name)
    return image


def icon(name: str, color: str, size: int = 14) -> ImageTk.PhotoImage:
    """`size` is in design pixels; the image is drawn at screen resolution."""

    key = (name, color, size, scale())
    if key not in _cache:
        target = px(size)
        picture = _draw(name, target, color).resize((target, target), Image.LANCZOS)
        _cache[key] = ImageTk.PhotoImage(picture)
    return _cache[key]
