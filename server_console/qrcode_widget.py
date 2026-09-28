"""Local, offline QR code generation for the mobile URL (segno; no network call)."""

from __future__ import annotations

import io
import tkinter as tk

import segno


def qr_photo_image(text: str, *, scale: int = 6, border: int = 2) -> tk.PhotoImage:
    qr = segno.make(text, error="m")
    buffer = io.BytesIO()
    qr.save(buffer, kind="png", scale=scale, border=border, dark="#1a1a1a", light="#ffffff")
    buffer.seek(0)
    return tk.PhotoImage(data=buffer.read())
