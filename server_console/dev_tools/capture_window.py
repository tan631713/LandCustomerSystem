"""Dev/test only: save a full-resolution PNG of the console window.

Uses PrintWindow, so the window does not need to be in front (a background
process cannot steal the foreground on Windows anyway).

usage: python capture_window.py OUT.png [--mock MOCK.png] [--title "..."]
With --mock, also writes OUT_side_by_side.png (mock left, capture right).
"""

import ctypes
import sys
from ctypes import wintypes

from PIL import Image

ctypes.windll.shcore.SetProcessDpiAwareness(2)
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

user32.GetWindowDC.restype = ctypes.c_void_p
user32.GetWindowDC.argtypes = [wintypes.HWND]
user32.ReleaseDC.argtypes = [wintypes.HWND, ctypes.c_void_p]
user32.PrintWindow.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.UINT]
gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
gdi32.CreateCompatibleBitmap.restype = ctypes.c_void_p
gdi32.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
gdi32.SelectObject.restype = ctypes.c_void_p
gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
gdi32.GetDIBits.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT, wintypes.UINT,
    ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT,
]
gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
gdi32.DeleteDC.argtypes = [ctypes.c_void_p]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


def find_window(title: str):
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _lparam):
        length = user32.GetWindowTextLengthW(hwnd)
        if length and user32.IsWindowVisible(hwnd):
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            if buffer.value == title:
                found.append(hwnd)
        return True

    user32.EnumWindows(callback, 0)
    return found[0] if found else None


def capture(hwnd) -> Image.Image:
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    width, height = rect.right - rect.left, rect.bottom - rect.top
    window_dc = user32.GetWindowDC(hwnd)
    memory_dc = gdi32.CreateCompatibleDC(window_dc)
    bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
    gdi32.SelectObject(memory_dc, bitmap)
    user32.PrintWindow(hwnd, memory_dc, 2)  # PW_RENDERFULLCONTENT
    header = BITMAPINFOHEADER()
    header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    header.biWidth, header.biHeight = width, -height
    header.biPlanes, header.biBitCount = 1, 32
    buffer = ctypes.create_string_buffer(width * height * 4)
    gdi32.GetDIBits(memory_dc, bitmap, 0, height, buffer, ctypes.byref(header), 0)
    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(memory_dc)
    user32.ReleaseDC(hwnd, window_dc)
    picture = Image.frombuffer("RGBA", (width, height), buffer, "raw", "BGRA", 0, 1).convert("RGB")
    # 只留客戶區：去掉作業系統的標題列與邊框，模擬圖本來就沒有這些。
    client = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(client))
    origin = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(origin))
    left, top = origin.x - rect.left, origin.y - rect.top
    return picture.crop((left, top, left + client.right, top + client.bottom))


def main():
    args = sys.argv[1:]
    out = args[0]
    title = args[args.index("--title") + 1] if "--title" in args else "Land Customer System 伺服器控制台"
    mock = args[args.index("--mock") + 1] if "--mock" in args else None
    hwnd = find_window(title)
    if not hwnd:
        print("window not found")
        return 1
    shot = capture(hwnd)
    shot.save(out)
    print("saved", out, shot.size)
    if mock:
        picture = Image.open(mock).convert("RGB")
        height = 1300
        left_image = picture.resize((int(picture.width * height / picture.height), height))
        right_image = shot.resize((int(shot.width * height / shot.height), height))
        canvas = Image.new("RGB", (left_image.width + right_image.width + 30, height), "#888888")
        canvas.paste(left_image, (0, 0))
        canvas.paste(right_image, (left_image.width + 30, 0))
        side = out.rsplit(".", 1)[0] + "_side_by_side.png"
        canvas.save(side)
        print("saved", side)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
