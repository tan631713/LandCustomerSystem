"""Regenerate version_info_client.txt from customer_version.py before every
build, so the Windows EXE's embedded file-version resource (visible in
Explorer > Properties > Details, and in Windows' own crash reports) never
drifts out of sync with DESKTOP_CLIENT_VERSION again.

This file went stale for months (stuck at 1.9.18 while
DESKTOP_CLIENT_VERSION moved through a dozen releases up to 1.9.31), which
made a real production crash investigation harder: Windows' Application
Error event log entry reported "1.9.18.0" for a build that was actually
much newer, momentarily raising doubt about whether the right build was
even deployed.
"""

from pathlib import Path

from customer_version import DESKTOP_CLIENT_BUILD_DATE, DESKTOP_CLIENT_VERSION

OUTPUT_PATH = Path(__file__).resolve().parent / "version_info_client.txt"


def build_version_tuple(version_text):
    parts = [int(part) for part in str(version_text).split(".")]
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts[:4])


def main():
    version_tuple = build_version_tuple(DESKTOP_CLIENT_VERSION)
    content = f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={version_tuple!r},
    prodvers={version_tuple!r},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040404B0',
        [
          StringStruct('CompanyName', '土地資料系統'),
          StringStruct('FileDescription', '土地資料系統－公司筆電客戶端'),
          StringStruct('FileVersion', '{DESKTOP_CLIENT_VERSION}'),
          StringStruct('InternalName', 'LandCustomerSystem'),
          StringStruct('LegalCopyright', 'Copyright 2026'),
          StringStruct('OriginalFilename', 'LandCustomerSystem.exe'),
          StringStruct('ProductName', '土地資料系統－公司筆電客戶端'),
          StringStruct('ProductVersion', '{DESKTOP_CLIENT_VERSION}'),
          StringStruct('BuildDate', '{DESKTOP_CLIENT_BUILD_DATE}')
        ]
      )
    ]),
    VarFileInfo([VarStruct('Translation', [1028, 1200])])
  ]
)
"""
    OUTPUT_PATH.write_text(content, encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH} for version {DESKTOP_CLIENT_VERSION}")


if __name__ == "__main__":
    main()
