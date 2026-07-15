"""Windows-protected storage for the local PostgreSQL connection string."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from pathlib import Path


APP_DIRECTORY_NAME = "LandCustomerSystem"
PROTECTED_DSN_FILE_NAME = "postgres-dsn.dpapi"
_ENTROPY = b"LandCustomerSystem/PostgreSQL/v1"


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def default_protected_dsn_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    root = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return root / APP_DIRECTORY_NAME / PROTECTED_DSN_FILE_NAME


def _blob(value: bytes):
    buffer = ctypes.create_string_buffer(value)
    return (
        _DataBlob(
            len(value),
            ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)),
        ),
        buffer,
    )


def _require_windows():
    if os.name != "nt":
        raise OSError("DPAPI protected PostgreSQL settings are only available on Windows")


def protect_text(value: str) -> bytes:
    _require_windows()
    raw = str(value).encode("utf-8")
    input_blob, input_buffer = _blob(raw)
    entropy_blob, entropy_buffer = _blob(_ENTROPY)
    output_blob = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    success = crypt32.CryptProtectData(
        ctypes.byref(input_blob),
        "LandCustomerSystem PostgreSQL",
        ctypes.byref(entropy_blob),
        None,
        None,
        0,
        ctypes.byref(output_blob),
    )
    del input_buffer, entropy_buffer
    if not success:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(output_blob.pbData)


def unprotect_text(value: bytes) -> str:
    _require_windows()
    input_blob, input_buffer = _blob(bytes(value))
    entropy_blob, entropy_buffer = _blob(_ENTROPY)
    output_blob = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    success = crypt32.CryptUnprotectData(
        ctypes.byref(input_blob),
        None,
        ctypes.byref(entropy_blob),
        None,
        None,
        0,
        ctypes.byref(output_blob),
    )
    del input_buffer, entropy_buffer
    if not success:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData).decode("utf-8")
    finally:
        kernel32.LocalFree(output_blob.pbData)


def save_postgres_dsn(dsn: str, path: Path | str | None = None) -> Path:
    if not str(dsn).strip():
        raise ValueError("PostgreSQL DSN cannot be empty")
    destination = Path(path or default_protected_dsn_path()).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_bytes(protect_text(str(dsn).strip()))
    temporary.replace(destination)
    return destination


def load_postgres_dsn(path: Path | str | None = None) -> str:
    source = Path(path or default_protected_dsn_path()).resolve()
    if not source.exists():
        return ""
    return unprotect_text(source.read_bytes()).strip()
