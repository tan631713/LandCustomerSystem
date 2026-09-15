"""Generate offline_tile_manifest.txt -- the list of every map tile the
offline 桃園市 coverage needs (see customer_offline_map.py for the
coverage bounds/zoom range and the tile math).

Run this on a dev machine whenever the coverage area or zoom range
changes; the output is a small text file (one "z/x/y" per line) checked
into git and shipped with the app. It contains no image data -- actually
downloading the tiles onto a company laptop is download_offline_map_tiles.bat's
job, not this script's.
"""

from pathlib import Path

from customer_offline_map import OFFLINE_TILE_MANIFEST_FILENAME, iter_offline_tiles


def build_manifest_text():
    lines = [f"{z}/{x}/{y}" for z, x, y in iter_offline_tiles()]
    return "\n".join(lines) + "\n"


def main():
    manifest_path = Path(__file__).resolve().parent / OFFLINE_TILE_MANIFEST_FILENAME
    text = build_manifest_text()
    manifest_path.write_text(text, encoding="utf-8")
    tile_count = text.count("\n")
    print(f"Wrote {tile_count} tile entries to {manifest_path}")


if __name__ == "__main__":
    main()
