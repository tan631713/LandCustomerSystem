"""Offline map-tile support for the "地圖與地號視覺化" feature.

Context: the map dialog's tile layer (built in customer_productivity.py's
build_map_html()/MapLocationsDialog) has always needed a live network
connection -- both Leaflet.js itself (loaded from a CDN) and every map
tile (fetched live from the 國土測繪中心 WMTS service or CARTO) are
fetched over HTTP each time the map is opened. Explicit user request:
replace that with a fully local option covering 桃園市 (the only county
this business actually works land in), so the map still renders when the
network is unreliable, blocked by a firewall, or simply unavailable --
while keeping the existing live layers as a fallback for anywhere outside
that local coverage.

This module owns the pure tile-math (no Qt, no network) shared by:
  - generate_offline_tile_manifest.py, which lists every tile URL/path
    this coverage needs (run once on a dev machine, checked into git as
    a small text file).
  - download_offline_map_tiles.bat, which the end user runs once on the
    actual company laptop to populate the local tile cache from that
    manifest (curl.exe, not Python -- see that script's own docstring for
    why).
  - the map HTML itself, to know where to point its local tile layer and
    whether a given record's coordinates actually fall inside the cached
    coverage (so the UI can tell the user when they're outside it,
    instead of just silently showing blank tiles).
"""

import math
import sys
from pathlib import Path

from PySide6.QtCore import QUrl

# Approximate bounding box for 桃園市 (Taoyuan City), generous enough to
# cover the whole administrative area including its mountainous Fuxing
# District to the south and the Guanyin/Dayuan coastline -- deliberately
# a rectangle, not the real (concave) county boundary, since a WMTS tile
# grid has no concept of "outside a polygon" anyway. Adjust here (and
# regenerate the manifest) if coverage ever needs to grow to another
# county.
OFFLINE_COVERAGE_NAME = "桃園市"
OFFLINE_LAT_MIN = 24.62
OFFLINE_LAT_MAX = 25.07
OFFLINE_LON_MIN = 120.86
OFFLINE_LON_MAX = 121.35
OFFLINE_ZOOM_MIN = 12
OFFLINE_ZOOM_MAX = 16

# 國土測繪中心「通用電子地圖」WMTS -- same tile source as the existing
# live default layer (nlscLayer in build_map_html()), just cached
# locally instead of fetched every time.
NLSC_TILE_URL_TEMPLATE = (
    "https://wmts.nlsc.gov.tw/wmts/EMAP/default/GoogleMapsCompatible/{z}/{y}/{x}"
)

OFFLINE_TILE_DIRNAME = "offline_map_tiles"
OFFLINE_TILE_MANIFEST_FILENAME = "offline_tile_manifest.txt"


def deg2tile(lat_deg, lon_deg, zoom):
    """Standard slippy-map (Web Mercator) degrees -> tile x/y at zoom."""
    lat_rad = math.radians(lat_deg)
    n = 2.0 ** zoom
    x = int((lon_deg + 180.0) / 360.0 * n)
    y = int(
        (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n
    )
    # Clamp: a lat/lon right at (or just past, from float rounding) the
    # projection's edge can otherwise compute an out-of-range tile index.
    max_index = int(n) - 1
    return max(0, min(x, max_index)), max(0, min(y, max_index))


def tile_xy_range(lat_min, lat_max, lon_min, lon_max, zoom):
    """Inclusive (x_min, x_max, y_min, y_max) tile range covering a bbox.

    Latitude and Y are inverted (tile y grows southward, lat grows
    northward), so the max-lat corner gives the *smaller* y.
    """
    x_min, y_min = deg2tile(lat_max, lon_min, zoom)
    x_max, y_max = deg2tile(lat_min, lon_max, zoom)
    return x_min, x_max, y_min, y_max


def iter_offline_tiles(
    *,
    lat_min=OFFLINE_LAT_MIN,
    lat_max=OFFLINE_LAT_MAX,
    lon_min=OFFLINE_LON_MIN,
    lon_max=OFFLINE_LON_MAX,
    zoom_min=OFFLINE_ZOOM_MIN,
    zoom_max=OFFLINE_ZOOM_MAX,
):
    """Yield every (z, x, y) tile the offline coverage needs, in order."""
    for zoom in range(zoom_min, zoom_max + 1):
        x_min, x_max, y_min, y_max = tile_xy_range(lat_min, lat_max, lon_min, lon_max, zoom)
        for x in range(x_min, x_max + 1):
            for y in range(y_min, y_max + 1):
                yield zoom, x, y


def is_within_offline_coverage(
    lat,
    lon,
    *,
    lat_min=OFFLINE_LAT_MIN,
    lat_max=OFFLINE_LAT_MAX,
    lon_min=OFFLINE_LON_MIN,
    lon_max=OFFLINE_LON_MAX,
):
    """True if a coordinate falls inside the cached-tile bounding box.

    A bounding-box check, not a real 桃園市 boundary check -- matches
    the tile grid itself (see the module docstring), so a coordinate
    that passes this really does have cached tiles available for it.
    """
    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        return False
    return lat_min <= lat <= lat_max and lon_min <= lon <= lon_max


def tile_url(template, z, x, y):
    return template.format(z=z, x=x, y=y)


def tile_relative_path(z, x, y):
    """Where a tile lives under the offline tile cache root, POSIX-style
    (Leaflet's tileLayer URL template always uses forward slashes,
    regardless of host OS)."""
    return f"{z}/{x}/{y}.png"


def resource_dir():
    """Where bundled, read-only app resources (like the vendored Leaflet
    assets) live -- PyInstaller's extracted _MEIPASS when frozen, the
    source tree otherwise. Duplicates customer_ui_qt.get_resource_dir()
    rather than importing it: customer_ui_qt.py imports from
    customer_productivity.py (which uses this module), so importing back
    would be a circular import.
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def leaflet_assets_dir():
    return resource_dir() / "assets" / "leaflet"


def offline_tile_cache_dir(app_directory):
    """Where downloaded offline tiles live -- a writable folder next to
    the EXE (APP_DIR), not the read-only bundled resource dir, and
    deliberately never created/populated by the app itself. It only
    exists once someone has run download_offline_map_tiles.bat, and it
    persists across app updates the same way attachments/backups do.
    """
    return Path(app_directory) / OFFLINE_TILE_DIRNAME


def offline_tile_cache_available(app_directory):
    """True once at least one tile has actually been downloaded.

    Cheap existence probe, not a completeness check -- used to decide
    whether the offline layer is worth offering (and defaulting to) at
    all, not to tell whether every tile the current view needs is
    present. A coordinate outside the cached bbox, or a zoom level
    outside OFFLINE_ZOOM_MIN..MAX, still just shows blank tiles on that
    layer -- see is_within_offline_coverage() for checking a specific
    coordinate ahead of time.
    """
    cache_dir = offline_tile_cache_dir(app_directory)
    if not cache_dir.is_dir():
        return False
    return any(cache_dir.rglob("*.png"))


def local_file_url(path):
    """A file:// URL for an absolute local path, as a plain string."""
    return QUrl.fromLocalFile(str(path)).toString()


def local_tile_url_template(app_directory):
    """The file:// URL template Leaflet's L.tileLayer needs for the
    offline cache, with the {z}/{x}/{y} placeholders intact.

    QUrl.fromLocalFile()/toString() percent-encodes literal "{"/"}"
    characters (they are not valid in a real file path), which breaks
    Leaflet's own placeholder substitution -- so the path is built and
    URL-escaped *without* the placeholders, then they are appended as a
    literal suffix rather than passed through QUrl at all.
    """
    cache_dir = offline_tile_cache_dir(app_directory)
    base_url = local_file_url(cache_dir)
    if not base_url.endswith("/"):
        base_url += "/"
    return base_url + "{z}/{x}/{y}.png"
