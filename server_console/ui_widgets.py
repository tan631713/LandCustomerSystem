"""Light native-Tk widgets for the console (see ui_theme.py for why).

Rules that keep the window cheap to build: one native window per widget,
rounded shapes are Pillow-rendered images on a canvas (antialiased, cached),
and every size/padding passes through `px()` so the layout matches the spec
at any display scale. Geometry arguments (`padx`, `pady`, ...) are scaled
automatically by the `Scaled*` mixins.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageDraw, ImageTk

from server_console.ui_icons import icon
from server_console.ui_theme import (
    BORDER, BROWN, BUTTON_BORDER, CARD_BG, GREEN, PRIMARY, RED, TEXT, TEXT_MUTED, WINDOW_BG,
    FONT_UI, blend, px, scaled_font,
)

BUTTON_STYLES = {
    # name: (fill, text, border, hover)
    "green": (GREEN, "#FFFFFF", None, "#17633A"),
    "red": (CARD_BG, RED, RED, "#FDF2F1"),
    "gray": (CARD_BG, TEXT, BUTTON_BORDER, "#F3F5F7"),
    "blue": (CARD_BG, PRIMARY, PRIMARY, "#EEF4FB"),
    "brown": (CARD_BG, BROWN, BROWN, "#FDF8EA"),
    "primary": (PRIMARY, "#FFFFFF", None, "#184D8C"),
    "dark": (CARD_BG, TEXT, TEXT, "#F3F5F7"),
}

_SUPERSAMPLE = 3
_image_cache: dict[tuple, ImageTk.PhotoImage] = {}


def bg_of(widget) -> str:
    """The colour a child of `widget` should use as its own background."""

    node = widget
    while node is not None:
        inner = getattr(node, "inner_bg", None)
        if inner:
            return inner
        try:
            color = str(node.cget("bg"))
        except tk.TclError:
            node = getattr(node, "master", None)
            continue
        if color.startswith("#") and len(color) == 7:
            return color
        try:  # a named/system colour such as "systembuttonface": Pillow needs #RRGGBB
            red, green, blue = node.winfo_rgb(color)
            return "#{:02X}{:02X}{:02X}".format(red >> 8, green >> 8, blue >> 8)
        except tk.TclError:
            return WINDOW_BG
    return WINDOW_BG


def _remember(key: tuple, build) -> ImageTk.PhotoImage:
    """Cached PhotoImage. The cache may be trimmed, so every widget must also keep
    a reference to the image it is showing (Tk drops an image when Python does)."""

    if key not in _image_cache:
        if len(_image_cache) > 300:
            _image_cache.clear()
        _image_cache[key] = ImageTk.PhotoImage(build())
    return _image_cache[key]


def rounded_image(width, height, radius, fill, border, border_width, backdrop) -> Image.Image:
    """Antialiased rounded rectangle, pre-composited on `backdrop` (all in screen px)."""

    width, height = max(2, int(width)), max(2, int(height))
    ss = _SUPERSAMPLE
    big = Image.new("RGB", (width * ss, height * ss), backdrop)
    draw = ImageDraw.Draw(big)
    box = (0, 0, width * ss - 1, height * ss - 1)
    radius = min(radius, width // 2, height // 2)
    if border and border_width:
        draw.rounded_rectangle(box, radius=radius * ss, fill=border)
        inset = border_width * ss
        draw.rounded_rectangle(
            (inset, inset, width * ss - 1 - inset, height * ss - 1 - inset),
            radius=max(0, radius * ss - inset), fill=fill,
        )
    else:
        draw.rounded_rectangle(box, radius=radius * ss, fill=fill)
    return big.resize((width, height), Image.LANCZOS)


def _scale_pad(value):
    if isinstance(value, (tuple, list)):
        return tuple(px(item) for item in value)
    return px(value)


def _scale_geometry(kwargs: dict) -> dict:
    for key in ("padx", "pady", "ipadx", "ipady"):
        if kwargs.get(key) is not None:
            kwargs[key] = _scale_pad(kwargs[key])
    return kwargs


class ScaledGeometry:
    """Geometry-manager arguments are given in design pixels."""

    def pack(self, **kwargs):
        return super().pack_configure(**_scale_geometry(kwargs))

    def grid(self, **kwargs):
        return super().grid_configure(**_scale_geometry(kwargs))

    def grid_columnconfigure(self, index, cnf=None, **kwargs):
        if kwargs.get("minsize"):
            kwargs["minsize"] = px(kwargs["minsize"])
        return super().grid_columnconfigure(index, cnf or {}, **kwargs)

    def grid_rowconfigure(self, index, cnf=None, **kwargs):
        if kwargs.get("minsize"):
            kwargs["minsize"] = px(kwargs["minsize"])
        return super().grid_rowconfigure(index, cnf or {}, **kwargs)

    columnconfigure = grid_columnconfigure
    rowconfigure = grid_rowconfigure


class Box(ScaledGeometry, tk.Frame):
    """Plain container. `width`/`height` are design pixels (0 = fit content)."""

    def __init__(self, master, bg=None, width=0, height=0):
        super().__init__(
            master, bg=bg or bg_of(master), bd=0, highlightthickness=0,
            width=px(width), height=px(height),
        )


class Label(ScaledGeometry, tk.Label):
    def __init__(self, master, text="", size=14, weight="normal", color=TEXT, bg=None, family=FONT_UI,
                 anchor="w", justify="left", wraplength=0, image=None, padx=0, pady=0, width=0, cursor=""):
        kwargs = {"image": image} if image is not None else {}
        if width:
            kwargs["width"] = width
        super().__init__(
            master, text=text, font=scaled_font(size, weight, family), fg=color, bg=bg or bg_of(master),
            anchor=anchor, justify=justify, wraplength=px(wraplength) if wraplength else 0,
            bd=0, highlightthickness=0, padx=px(padx), pady=px(pady), cursor=cursor, **kwargs,
        )
        self._size, self._weight, self._family = size, weight, family

    def configure(self, cnf=None, **kwargs):
        if "text_color" in kwargs:
            kwargs["fg"] = kwargs.pop("text_color")
        if "wraplength" in kwargs:
            kwargs["wraplength"] = px(kwargs["wraplength"]) if kwargs["wraplength"] else 0
        if "weight" in kwargs:
            self._weight = kwargs.pop("weight")
            kwargs["font"] = scaled_font(self._size, self._weight, self._family)
        return super().configure(cnf, **kwargs)

    config = configure

    def set_wrap_px(self, screen_pixels: int) -> None:
        """Wrap width already in screen pixels (from a <Configure> event)."""

        super().configure(wraplength=max(0, int(screen_pixels)))


def circle_photo(diameter, fill, outline, outline_width, backdrop) -> ImageTk.PhotoImage:
    """Antialiased disc (or ring when `outline` is set); sizes in screen px."""

    key = ("dot", diameter, fill, outline, outline_width, backdrop)

    def build():
        d, ss = diameter, _SUPERSAMPLE * 2
        big = Image.new("RGB", (d * ss, d * ss), backdrop)
        draw = ImageDraw.Draw(big)
        if outline and outline_width:
            draw.ellipse((0, 0, d * ss - 1, d * ss - 1), fill=outline)
            inset = outline_width * ss
            draw.ellipse((inset, inset, d * ss - 1 - inset, d * ss - 1 - inset), fill=fill)
        else:
            draw.ellipse((0, 0, d * ss - 1, d * ss - 1), fill=fill)
        return big.resize((d, d), Image.LANCZOS)

    return _remember(key, build)


class Dot(tk.Canvas):
    """Antialiased circle (optionally a ring) with an optional centred digit."""

    def __init__(self, master, diameter, fill, outline=None, outline_width=0, text="", text_color=TEXT,
                 text_size=12, bg=None):
        self._diameter = px(diameter)
        super().__init__(master, width=self._diameter, height=self._diameter, bg=bg or bg_of(master),
                         highlightthickness=0, bd=0)
        self._outline_width = px(outline_width) if outline_width else 0
        self._image_item = self.create_image(0, 0, anchor="nw")
        self._text_item = self.create_text(
            self._diameter / 2, self._diameter / 2, text=text, fill=text_color,
            font=scaled_font(text_size, "bold"),
        )
        self.set(fill, outline, text_color, text)

    def set(self, fill, outline=None, text_color=None, text=None, bg=None):
        backdrop = bg or self.cget("bg")
        if bg:
            self.configure(bg=bg)
        self._photo = circle_photo(self._diameter, fill, outline, self._outline_width, backdrop)
        self.itemconfigure(self._image_item, image=self._photo)
        options = {}
        if text_color is not None:
            options["fill"] = text_color
        if text is not None:
            options["text"] = text
        if options:
            self.itemconfigure(self._text_item, **options)


class RoundedFrame(ScaledGeometry, tk.Canvas):
    """Rounded, bordered container. Children are packed/gridded into it directly;
    the shape is a few canvas items (edge rectangles + four Pillow corner tiles)
    so resizing is just `coords()` calls."""

    def __init__(self, master, fill=CARD_BG, border=BORDER, border_width=1, radius=10, backdrop=None):
        self.inner_bg = fill
        self._border = border
        self._border_width = px(border_width) if border and border_width else 0
        self._radius = px(radius)
        self._backdrop = backdrop or bg_of(master)
        super().__init__(master, bg=self._backdrop, width=1, height=1, highlightthickness=0, bd=0)
        self._items: dict[str, int] = {}
        for name in ("fill_center", "fill_left", "fill_right", "edge_top", "edge_bottom", "edge_left", "edge_right"):
            self._items[name] = self.create_rectangle(0, 0, 0, 0, width=0)
        for name in ("tl", "tr", "bl", "br"):
            self._items[name] = self.create_image(0, 0, anchor="nw")
        self._size = (0, 0)
        self.bind("<Configure>", self._on_configure, add="+")
        self._apply_colors()

    def set_colors(self, fill=None, border=None, backdrop=None):
        if fill is not None:
            self.inner_bg = fill
        if border is not None:
            self._border = border
        if backdrop is not None:
            self._backdrop = backdrop
            self.configure(bg=backdrop)
        self._apply_colors()
        self._layout_shape(force=True)

    def _apply_colors(self):
        r, bw = self._radius, self._border_width
        key = ("corners", r, self.inner_bg, self._border, bw, self._backdrop)

        def tiles():
            size = max(2, 2 * r)
            picture = rounded_image(size, size, r, self.inner_bg, self._border, bw, self._backdrop)
            return {
                "tl": picture.crop((0, 0, r, r)), "tr": picture.crop((r, 0, 2 * r, r)),
                "bl": picture.crop((0, r, r, 2 * r)), "br": picture.crop((r, r, 2 * r, 2 * r)),
            }

        self._corner_photos = {name: ImageTk.PhotoImage(image) for name, image in tiles().items()}
        for name, image in self._corner_photos.items():
            self.itemconfigure(self._items[name], image=image)
        for name in ("fill_center", "fill_left", "fill_right"):
            self.itemconfigure(self._items[name], fill=self.inner_bg)
        for name in ("edge_top", "edge_bottom", "edge_left", "edge_right"):
            self.itemconfigure(self._items[name], fill=self._border or self.inner_bg,
                               state="normal" if bw else "hidden")

    def _on_configure(self, event):
        self._layout_shape()

    def _layout_shape(self, force=False):
        w, h = self.winfo_width(), self.winfo_height()
        if w <= 1 or h <= 1 or (not force and (w, h) == self._size):
            return
        self._size = (w, h)
        r, bw = self._radius, self._border_width
        coords = self.coords
        items = self._items
        coords(items["fill_center"], r, 0, w - r, h)
        coords(items["fill_left"], 0, r, r, h - r)
        coords(items["fill_right"], w - r, r, w, h - r)
        coords(items["edge_top"], r, 0, w - r, bw)
        coords(items["edge_bottom"], r, h - bw, w - r, h)
        coords(items["edge_left"], 0, r, bw, h - r)
        coords(items["edge_right"], w - bw, r, w, h - r)
        coords(items["tl"], 0, 0)
        coords(items["tr"], w - r, 0)
        coords(items["bl"], 0, h - r)
        coords(items["br"], w - r, h - r)


def restyle_children(widget, old_bg: str, new_bg: str) -> None:
    """After a container's background changed, follow it in every descendant
    that used the old colour."""

    for child in widget.winfo_children():
        try:
            if child.cget("bg") == old_bg:
                child.configure(bg=new_bg)
        except tk.TclError:
            pass
        if hasattr(child, "set_backdrop"):
            child.set_backdrop(new_bg)
        restyle_children(child, old_bg, new_bg)


class Panel(RoundedFrame):
    """A card that draws its own text on the card canvas (one native window
    instead of one per label). Coordinates and sizes are design pixels."""

    def text(self, x, y, text="", size=14, weight="normal", color=TEXT, anchor="w", family=FONT_UI,
             width=0, justify="left"):
        return self.create_text(
            px(x), px(y), text=text, anchor=anchor, fill=color, font=scaled_font(size, weight, family),
            width=px(width) if width else 0, justify=justify,
        )

    def text_height(self, item) -> int:
        box = self.bbox(item)
        return (box[3] - box[1]) if box else 0


class CanvasButton(tk.Canvas):
    """Rounded button in a single native window. Disabled = the spec's 45 %
    look (colours mixed into the backdrop; Tk cannot make a widget translucent)."""

    def __init__(self, master, text, command, style="gray", icon_name=None, height=44, width=0,
                 font_size=14, backdrop=None, radius=8, texts=()):
        self._palette = BUTTON_STYLES[style]
        self._command = command
        self._icon_name = icon_name
        self._icon_size = 14 if height >= 40 else 12
        self._backdrop = backdrop or bg_of(master)
        self._radius = px(radius)
        self._font = scaled_font(font_size)
        self._text = text
        self._enabled = True
        self._hover = False
        self._extra_texts = tuple(texts)
        self._natural_width = 0
        self._requested = (max(px(width), self._natural(text)), px(height))
        super().__init__(master, width=self._requested[0], height=self._requested[1], bg=self._backdrop,
                         highlightthickness=0, bd=0, cursor="hand2", takefocus=1)
        self._bg_item = self.create_image(0, 0, anchor="nw")
        self._icon_item = self.create_image(0, 0, anchor="w") if icon_name else None
        self._text_item = self.create_text(0, 0, anchor="w", text=text, font=self._font)
        self._size = (0, 0)
        self.bind("<Configure>", lambda _e: self._render(), add="+")
        self.bind("<Enter>", lambda _e: self._set_hover(True))
        self.bind("<Leave>", lambda _e: self._set_hover(False))
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Return>", lambda _e: self._invoke())
        self.bind("<space>", lambda _e: self._invoke())
        self._render()

    # --- sizing -----------------------------------------------------------
    def _text_width(self, text: str) -> int:
        return self._font.measure(text)

    def _natural(self, text: str) -> int:
        widest = max(self._text_width(item) for item in (text, *self._extra_texts))
        icon_part = px(self._icon_size) + px(7) if self._icon_name else 0
        return 2 * px(16) + icon_part + widest

    # --- state --------------------------------------------------------------
    def set_enabled(self, enabled: bool) -> None:
        if enabled == self._enabled:
            return
        self._enabled = enabled
        self._hover = False
        self.configure(cursor="hand2" if enabled else "arrow")
        self._render()

    def set_label(self, text: str) -> None:
        if text == self._text:
            return
        self._text = text
        self.configure(width=max(self._requested[0], self._natural(text)))
        self._render()

    def set_backdrop(self, color: str) -> None:
        self._backdrop = color
        self.configure(bg=color)
        self._render()

    def _set_hover(self, hover: bool) -> None:
        if self._enabled and hover != self._hover:
            self._hover = hover
            self._render()

    def _on_release(self, event) -> None:
        if self._enabled and 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height():
            self._invoke()

    def _invoke(self) -> None:
        if self._enabled and self._command:
            self._command()

    # --- drawing ------------------------------------------------------------
    def _colors(self):
        fill, text_color, border, hover = self._palette
        if not self._enabled:
            backdrop = self._backdrop
            return (blend(fill, backdrop, 0.45), blend(text_color, backdrop, 0.45),
                    blend(border, backdrop, 0.45) if border else None)
        return (hover if self._hover else fill, text_color, border)

    def _render(self) -> None:
        w, h = self.winfo_width(), self.winfo_height()
        if w <= 1 or h <= 1:
            w, h = int(self.cget("width")), int(self.cget("height"))
        fill, text_color, border = self._colors()
        bw = px(1) if border else 0
        key = ("button", w, h, self._radius, fill, border, bw, self._backdrop)
        self._photo = _remember(key, lambda: rounded_image(w, h, self._radius, fill, border, bw, self._backdrop))
        self.itemconfigure(self._bg_item, image=self._photo)
        text_width = self._text_width(self._text)
        if self._icon_item is not None:
            gap, icon_width = px(7), px(self._icon_size)
            left = (w - (icon_width + gap + text_width)) / 2
            self.coords(self._icon_item, left, h / 2)
            self._icon_photo = icon(self._icon_name, text_color, self._icon_size)
            self.itemconfigure(self._icon_item, image=self._icon_photo)
            self.coords(self._text_item, left + icon_width + gap, h / 2)
        else:
            self.coords(self._text_item, (w - text_width) / 2, h / 2)
        self.itemconfigure(self._text_item, text=self._text, fill=text_color)


class CanvasCheck(tk.Canvas):
    """Checkbox + label in one window (blue box with a white tick when on)."""

    def __init__(self, master, text, variable, command=None, font_size=13, bg=None):
        self._variable = variable
        self._command = command
        self._font = scaled_font(font_size)
        self._box = px(18)
        self._gap = px(8)
        background = bg or bg_of(master)
        width = self._box + self._gap + self._font.measure(text) + px(2)
        super().__init__(master, width=width, height=max(self._box, self._font.metrics("linespace")) + px(2),
                         bg=background, highlightthickness=0, bd=0, cursor="hand2", takefocus=1)
        self._image_item = self.create_image(0, int(self.cget("height")) / 2, anchor="w")
        self.create_text(self._box + self._gap, int(self.cget("height")) / 2, anchor="w", text=text,
                         font=self._font, fill=TEXT)
        self._background = background
        self.bind("<ButtonRelease-1>", lambda _e: self._toggle())
        self.bind("<space>", lambda _e: self._toggle())
        variable.trace_add("write", lambda *_: self._render())
        self._render()

    def _toggle(self) -> None:
        self._variable.set(not self._variable.get())
        if self._command:
            self._command()

    def _render(self) -> None:
        on = bool(self._variable.get())
        size, background = self._box, self._background
        key = ("check", size, on, background)

        def build():
            ss = _SUPERSAMPLE * 2
            big = Image.new("RGB", (size * ss, size * ss), background)
            draw = ImageDraw.Draw(big)
            radius = px(4) * ss
            edge = (0, 0, size * ss - 1, size * ss - 1)
            if on:
                draw.rounded_rectangle(edge, radius=radius, fill=PRIMARY)
                u = size * ss / 18
                draw.line([(4.6 * u, 9.4 * u), (7.8 * u, 12.6 * u), (13.4 * u, 5.8 * u)], fill="#FFFFFF",
                          width=max(2, int(2 * u)), joint="curve")
            else:
                draw.rounded_rectangle(edge, radius=radius, fill=BUTTON_BORDER)
                inset = max(1, int(1.5 * ss * size / 18))
                draw.rounded_rectangle((inset, inset, size * ss - 1 - inset, size * ss - 1 - inset),
                                       radius=max(0, radius - inset), fill="#FFFFFF")
            return big.resize((size, size), Image.LANCZOS)

        self._photo = _remember(key, build)
        self.itemconfigure(self._image_item, image=self._photo)


class RoundedEntry(tk.Canvas):
    """34px input with a rounded 1px border that turns blue on focus."""

    def __init__(self, master, textvariable, *, secret=False, placeholder="", height=34, radius=6, font_size=14):
        self._backdrop = bg_of(master)
        self._radius = px(radius)
        self._height = px(height)
        self._font = scaled_font(font_size)
        self._focused = False
        self._size = (0, 0)
        super().__init__(master, width=1, height=self._height, bg=self._backdrop, highlightthickness=0, bd=0)
        self.entry = tk.Entry(
            self, textvariable=textvariable, bd=0, highlightthickness=0, relief="flat", bg=CARD_BG, fg=TEXT,
            insertbackground=TEXT, font=self._font, show="•" if secret else "",
        )
        self._bg_item = self.create_image(0, 0, anchor="nw")
        self._pad = px(10)
        self._win_item = self.create_window(self._pad, self._height / 2, anchor="w", window=self.entry)
        self._placeholder = self.create_text(
            self._pad + px(1), self._height / 2, anchor="w", text=placeholder, fill=TEXT_MUTED, font=self._font,
        )
        self._variable = textvariable
        textvariable.trace_add("write", lambda *_: self._sync_placeholder())
        self.entry.bind("<FocusIn>", lambda _e: self._focus(True))
        self.entry.bind("<FocusOut>", lambda _e: self._focus(False))
        self.bind("<Button-1>", lambda _e: self.entry.focus_set())
        self.tag_bind(self._placeholder, "<Button-1>", lambda _e: self.entry.focus_set())
        self.bind("<Configure>", lambda _e: self._render(), add="+")
        self._sync_placeholder()

    def _focus(self, focused: bool) -> None:
        self._focused = focused
        self._render(force=True)
        self._sync_placeholder()

    def _sync_placeholder(self) -> None:
        empty = not self._variable.get()
        self.itemconfigure(self._placeholder, state="normal" if empty and not self._focused else "hidden")

    def _render(self, force=False) -> None:
        w, h = self.winfo_width(), self.winfo_height()
        if w <= 1 or h <= 1 or (not force and (w, h) == self._size):
            return
        self._size = (w, h)
        border = PRIMARY if self._focused else BUTTON_BORDER
        key = ("entry", w, h, self._radius, border, self._backdrop)
        self._photo = _remember(key, lambda: rounded_image(w, h, self._radius, CARD_BG, border, px(1), self._backdrop))
        self.itemconfigure(self._bg_item, image=self._photo)
        self.itemconfigure(self._win_item, width=max(10, w - 2 * self._pad))

    def focus_entry(self) -> None:
        self.entry.focus_set()


class Dropdown(tk.Canvas):
    """Read-only pick list drawn like RoundedEntry, opening a native popup menu."""

    def __init__(self, master, values, *, height=34, radius=6, font_size=14, command=None):
        self._backdrop = bg_of(master)
        self._radius = px(radius)
        self._height = px(height)
        self._font = scaled_font(font_size)
        self._values = list(values)
        self._value = self._values[0] if self._values else ""
        self._command = command
        self._size = (0, 0)
        super().__init__(master, width=1, height=self._height, bg=self._backdrop, highlightthickness=0, bd=0,
                         cursor="hand2")
        self._bg_item = self.create_image(0, 0, anchor="nw")
        self._text_item = self.create_text(px(10), self._height / 2, anchor="w", text=self._value,
                                           font=self._font, fill=TEXT)
        self._arrow = self.create_line(0, 0, 0, 0, 0, 0, fill=TEXT_MUTED, width=px(1.6), joinstyle="miter")
        self.bind("<Configure>", lambda _e: self._render(), add="+")
        self.bind("<ButtonRelease-1>", lambda _e: self._open())

    def get(self) -> str:
        return self._value

    def set(self, value: str) -> None:
        self._value = value
        self._fit_text()

    def configure_values(self, values) -> None:
        self._values = list(values)

    def _fit_text(self) -> None:
        available = max(20, self.winfo_width() - px(10) - px(28))
        text = self._value
        while text and self._font.measure(text) > available and len(text) > 1:
            text = text[:-2] + "…" if not text.endswith("…") else text[:-2] + "…"
        self.itemconfigure(self._text_item, text=text)

    def _render(self) -> None:
        w, h = self.winfo_width(), self.winfo_height()
        if w <= 1 or h <= 1 or (w, h) == self._size:
            return
        self._size = (w, h)
        key = ("entry", w, h, self._radius, BUTTON_BORDER, self._backdrop)
        self._photo = _remember(key, lambda: rounded_image(w, h, self._radius, CARD_BG, BUTTON_BORDER, px(1),
                                                           self._backdrop))
        self.itemconfigure(self._bg_item, image=self._photo)
        cx, cy, half = w - px(18), h / 2, px(4)
        self.coords(self._arrow, cx - half, cy - half / 2, cx, cy + half / 2, cx + half, cy - half / 2)
        self._fit_text()

    def _open(self) -> None:
        if not self._values:
            return
        menu = tk.Menu(self, tearoff=0, font=self._font, bg=CARD_BG, fg=TEXT, activebackground=PRIMARY,
                       activeforeground="#FFFFFF", bd=0)
        for value in self._values:
            menu.add_command(label=value, command=lambda v=value: self._choose(v))
        try:
            menu.tk_popup(self.winfo_rootx(), self.winfo_rooty() + self.winfo_height())
        finally:
            menu.grab_release()

    def _choose(self, value: str) -> None:
        self.set(value)
        if self._command:
            self._command(value)


def fit_text(font, text: str, max_pixels: int) -> str:
    """Longest prefix of `text` (plus "…") that fits in `max_pixels` for `font`."""

    if max_pixels <= 0 or font.measure(text) <= max_pixels:
        return text
    low, high = 0, len(text)
    while low < high:  # binary search for the longest prefix that still fits with the ellipsis
        middle = (low + high + 1) // 2
        if font.measure(text[:middle] + "…") <= max_pixels:
            low = middle
        else:
            high = middle - 1
    return text[:low] + "…" if low else "…"


def ellipsize(text: str, max_chars: int) -> str:
    """Cut to `max_chars` with a trailing "…" (monospace text only)."""

    if max_chars <= 1 or len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


class PageScroller(tk.Frame):
    """A frame whose content is at least as tall as the window (so weighted rows
    still fill the space) and scrolls when the window is shorter.

    The scrollbar floats over the right edge instead of taking a column: showing
    or hiding it must not change the content width, otherwise the width change
    can flip whether scrolling is needed and the layout oscillates forever."""

    def __init__(self, master, background=WINDOW_BG):
        super().__init__(master, bg=background)
        self.canvas = tk.Canvas(self, bg=background, highlightthickness=0, bd=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(fill="both", expand=True)
        self.content = Box(self.canvas, bg=background)
        self._window = self.canvas.create_window((0, 0), window=self.content, anchor="nw")
        self._scrollable = False
        self.canvas.bind("<Configure>", self._relayout)
        self.content.bind("<Configure>", self._relayout)

    def _relayout(self, _event=None):
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        needed = self.content.winfo_reqheight()
        target = max(height, needed)
        self.canvas.itemconfigure(self._window, width=width, height=target)
        self.canvas.configure(scrollregion=(0, 0, width, target))
        scrollable = needed > height + 1
        if scrollable != self._scrollable:
            self._scrollable = scrollable
            if scrollable:
                self.scrollbar.place(relx=1.0, rely=0.0, relheight=1.0, anchor="ne")
                self.scrollbar.lift()
            else:
                self.scrollbar.place_forget()
                self.canvas.yview_moveto(0)

    def is_scrollable(self) -> bool:
        return self._scrollable

    def contains(self, widget) -> bool:
        while widget is not None:
            if widget is self:
                return True
            widget = getattr(widget, "master", None)
        return False

    def scroll(self, event_delta: int) -> None:
        if self._scrollable:
            self.canvas.yview_scroll(-1 if event_delta > 0 else 1, "units")
