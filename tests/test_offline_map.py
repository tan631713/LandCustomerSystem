"""Tests for the offline map-tile feature: replacing the "地圖與地號視覺
化" map's live-network dependency (CDN-loaded Leaflet.js, live WMTS/CARTO
tiles) with a local 桃園市 tile cache -- explicit user request, motivated
by wanting the map to not depend on an external service (unreliable
network, a company firewall) rather than genuinely offline field use.
"""

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import customer_offline_map as offline_map
from customer_offline_map import (
    deg2tile,
    is_within_offline_coverage,
    iter_offline_tiles,
    leaflet_assets_dir,
    local_file_url,
    local_tile_url_template,
    offline_tile_cache_available,
    offline_tile_cache_dir,
    tile_xy_range,
)
from customer_productivity import render_map_html_document


class TileMathTests(unittest.TestCase):
    def test_deg2tile_matches_known_taoyuan_tile(self):
        # Independently verified against the standard slippy-map formula
        # during development (see the session's own spike test) -- 桃園
        # 區 at zoom 15 is tile (27425, 14033).
        self.assertEqual(deg2tile(24.9936, 121.3010, 15), (27425, 14033))

    def test_deg2tile_clamps_to_valid_range_at_the_projection_edge(self):
        z = 10
        max_index = 2 ** z - 1
        x, y = deg2tile(89.9, 179.9, z)
        self.assertTrue(0 <= x <= max_index)
        self.assertTrue(0 <= y <= max_index)

    def test_tile_xy_range_is_ordered_and_inverted_for_latitude(self):
        x_min, x_max, y_min, y_max = tile_xy_range(24.62, 25.07, 120.86, 121.35, 13)
        self.assertLessEqual(x_min, x_max)
        self.assertLessEqual(y_min, y_max)

    def test_iter_offline_tiles_covers_every_configured_zoom_level(self):
        zooms = {z for z, _x, _y in iter_offline_tiles(zoom_min=12, zoom_max=13)}
        self.assertEqual(zooms, {12, 13})

    def test_is_within_offline_coverage_checks_the_bounding_box(self):
        self.assertTrue(is_within_offline_coverage(24.9936, 121.3010))  # 桃園區
        self.assertFalse(is_within_offline_coverage(25.0330, 121.5654))  # 台北市
        self.assertFalse(is_within_offline_coverage(None, None))
        self.assertFalse(is_within_offline_coverage("not-a-number", 121.3))


class LocalAssetPathTests(unittest.TestCase):
    def test_leaflet_assets_are_vendored_in_the_repo(self):
        assets_dir = leaflet_assets_dir()
        self.assertTrue((assets_dir / "leaflet.js").is_file())
        self.assertTrue((assets_dir / "leaflet.css").is_file())

    def test_local_file_url_produces_a_file_scheme_url(self):
        url = local_file_url(leaflet_assets_dir() / "leaflet.js")
        self.assertTrue(url.startswith("file://"))
        self.assertTrue(url.endswith("leaflet.js"))

    def test_local_tile_url_template_keeps_leaflet_placeholders_intact(self):
        template = local_tile_url_template(r"C:\LandCustomerSystem")
        self.assertIn("{z}", template)
        self.assertIn("{x}", template)
        self.assertIn("{y}", template)
        self.assertTrue(template.startswith("file://"))
        self.assertTrue(template.endswith("/{z}/{x}/{y}.png"))

    def test_offline_tile_cache_available_is_false_until_a_tile_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(offline_tile_cache_available(tmp))
            tile_path = offline_tile_cache_dir(tmp) / "12" / "3423" / "1753.png"
            tile_path.parent.mkdir(parents=True)
            tile_path.write_bytes(b"not a real png, existence is all that matters here")
            self.assertTrue(offline_tile_cache_available(tmp))


def _location(**overrides):
    base = {
        "district": "桃園區", "section": "一段", "subsection": "", "land_number": "100",
        "owner_name": "王小明", "latitude": 24.9936, "longitude": 121.3010,
    }
    base.update(overrides)
    return base


class RenderMapHtmlDocumentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_leaflet_assets_are_referenced_locally_not_from_a_cdn(self):
        with tempfile.TemporaryDirectory() as tmp:
            document, row_count = render_map_html_document([_location()], tmp)
        self.assertEqual(row_count, 1)
        # Leaflet itself must not come from a CDN -- the CARTO *tile*
        # layer staying a live basemaps.cartocdn.com URL is fine and
        # expected, it is deliberately kept as an online fallback layer.
        self.assertNotIn("unpkg.com", document)
        self.assertIn("file://", document)
        self.assertIn('href="file://', document)  # leaflet.css
        self.assertIn('src="file://', document)  # leaflet.js

    def test_offline_layer_is_default_only_once_a_tile_actually_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            document_without, _ = render_map_html_document([_location()], tmp)
            self.assertNotIn("本地離線地圖", document_without)
            self.assertIn('layers: [nlscLayer]', document_without)

            tile_path = offline_tile_cache_dir(tmp) / "15" / "27425" / "14033.png"
            tile_path.parent.mkdir(parents=True)
            tile_path.write_bytes(b"fixture")
            document_with, _ = render_map_html_document([_location()], tmp)
        self.assertIn("本地離線地圖", document_with)
        self.assertIn('layers: [offlineLayer]', document_with)

    def test_online_layers_stay_available_as_a_fallback_when_offline_is_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            tile_path = offline_tile_cache_dir(tmp) / "15" / "27425" / "14033.png"
            tile_path.parent.mkdir(parents=True)
            tile_path.write_bytes(b"fixture")
            document, _ = render_map_html_document([_location()], tmp)
        self.assertIn("wmts.nlsc.gov.tw", document)
        self.assertIn("basemaps.cartocdn.com", document)

    def test_offline_layer_uses_min_native_zoom_not_min_zoom(self):
        # Real user report: the map's default "全部" view fits every
        # district's markers at once, which needs a much lower zoom than
        # the cache's z12 floor -- minZoom would leave the layer showing
        # nothing at all below that (a blank grey box, no error), while
        # minNativeZoom instead stretches the z12 tiles to cover it.
        with tempfile.TemporaryDirectory() as tmp:
            tile_path = offline_tile_cache_dir(tmp) / "12" / "3423" / "1753.png"
            tile_path.parent.mkdir(parents=True)
            tile_path.write_bytes(b"fixture")
            document, _ = render_map_html_document([_location()], tmp)
        offline_layer_js = document[document.index("const offlineLayer"):document.index("const nlscLayer")]
        self.assertIn("minNativeZoom: 12", offline_layer_js)
        # "minZoom:" (the property, with its colon) -- not a bare
        # substring check, which would also match the explanatory
        # comment's own prose mentioning "minZoom" by name.
        self.assertNotIn("minZoom:", offline_layer_js)

    def test_rows_with_no_coordinates_are_excluded_but_do_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            document, row_count = render_map_html_document(
                [_location(), _location(latitude=None, longitude=None)], tmp
            )
        self.assertEqual(row_count, 1)
        self.assertIn("王小明", document)


class EmbeddedMapViewTests(unittest.TestCase):
    """End-to-end check that QWebEngineView can actually render the
    generated document with real local tiles -- not just that the HTML
    *string* looks right. This is the one part of the feature that
    genuinely surprised us during development (see the session's own
    spike notes): a page loaded via setHtml() with a non-file:// origin
    silently fails to load *any* local file:// resource, Leaflet.js
    included, so a purely string-level test would have missed a real
    blank-map bug. Uses a synthetic PNG (Pillow, already a project
    dependency) instead of a real downloaded tile so this test needs no
    network access.
    """

    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_offline_tile_actually_loads_in_the_embedded_view(self):
        from PIL import Image
        from PySide6.QtCore import QEventLoop, QTimer, QUrl
        from PySide6.QtWebEngineWidgets import QWebEngineView

        with tempfile.TemporaryDirectory() as tmp:
            # A single-marker map's fitBounds() call (see
            # render_map_html_document()'s showDistrict()) zooms all the
            # way to its own maxZoom (17), not the marker's "natural"
            # zoom -- so the fixture tiles need to be there, not at some
            # other zoom level. A small grid around the exact center tile
            # covers any minor padding/viewport rounding.
            center_x, center_y = deg2tile(24.9936, 121.3010, 17)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    tile_path = (
                        offline_tile_cache_dir(tmp)
                        / "17" / str(center_x + dx) / f"{center_y + dy}.png"
                    )
                    tile_path.parent.mkdir(parents=True, exist_ok=True)
                    Image.new("RGB", (256, 256), color=(200, 220, 240)).save(tile_path)

            document, _row_count = render_map_html_document(
                [
                    {
                        "district": "桃園區", "section": "一段", "subsection": "",
                        "land_number": "100", "owner_name": "王小明",
                        "latitude": 24.9936, "longitude": 121.3010,
                    }
                ],
                tmp,
            )

            view = QWebEngineView()
            # #map is width:100% -- with no explicit size the view (never
            # shown) can end up 0x0, which makes Leaflet correctly decide
            # there is nothing to load. A real QMainWindow always gives
            # it real pixels; this stands in for that here.
            view.resize(800, 600)
            loop = QEventLoop()
            result = {}

            def on_load_finished(ok):
                result["load_finished_ok"] = ok

                def check():
                    # Leaflet marks each <img> tile "leaflet-tile-loaded"
                    # once it actually loads -- checking the DOM this way
                    # (rather than adding test-only tracking globals to
                    # the production template) confirms the real tile
                    # file was fetched and rendered, not just that no JS
                    # error was thrown.
                    view.page().runJavaScript(
                        "JSON.stringify({"
                        "loadedTiles: document.querySelectorAll('.leaflet-tile-loaded').length, "
                        "hasLeaflet: typeof L !== 'undefined'"
                        "})",
                        lambda value: (result.update(js=value), loop.quit()),
                    )

                QTimer.singleShot(1500, check)

            view.loadFinished.connect(on_load_finished)
            view.setHtml(document, QUrl.fromLocalFile(str(tmp) + "/"))
            QTimer.singleShot(8000, loop.quit)
            loop.exec()

        self.assertTrue(result.get("load_finished_ok"))
        self.assertIn('"hasLeaflet":true', result.get("js", ""))
        self.assertNotIn('"loadedTiles":0', result.get("js", ""))

    def test_the_all_districts_view_still_shows_tiles_with_only_z12_downloaded(self):
        # Reproduces the actual user report (screenshot: a blank grey map
        # with the district tabs and zoom/layer controls, but no tiles at
        # all): with markers spread across the *whole* 桃園市 bounding
        # box -- not just a couple of nearby districts, which turned out
        # during debugging to still fit at zoom 17 and not exercise this
        # at all -- the default "全部" view's fitBounds() genuinely picks
        # a zoom around 10, well below the offline cache's z12 floor. The
        # old minZoom: 12 left the layer showing nothing at all below
        # that; minNativeZoom instead stretches the z12 tiles to cover
        # it. Only z12 tiles are downloaded here (no other zoom) so this
        # cannot pass by accident via some other zoom level having tiles.
        #
        # view.show() is required, not optional, for this one: an
        # unshown QWebEngineView (fine for the single-marker test above,
        # where a degenerate one-point fitBounds always picks maxZoom
        # regardless of container size) leaves <body> at clientWidth: 0
        # under the offscreen platform, which collapses the map container
        # and makes fitBounds pick an unrelated zoom -- an artifact of
        # this test harness, not something to fix in the app.
        from PIL import Image
        from PySide6.QtCore import QEventLoop, QTimer, QUrl
        from PySide6.QtWebEngineWidgets import QWebEngineView

        with tempfile.TemporaryDirectory() as tmp:
            for _z, x, y in iter_offline_tiles(zoom_min=12, zoom_max=12):
                tile_path = offline_tile_cache_dir(tmp) / "12" / str(x) / f"{y}.png"
                tile_path.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (256, 256), color=(200, 220, 240)).save(tile_path)

            locations = [
                _location(district="觀音區", latitude=24.65, longitude=120.90),
                _location(district="復興區", latitude=25.04, longitude=121.32),
            ]
            document, _row_count = render_map_html_document(locations, tmp)

            view = QWebEngineView()
            view.resize(800, 600)
            view.show()
            loop = QEventLoop()
            result = {}

            def on_load_finished(ok):
                result["load_finished_ok"] = ok

                def check():
                    view.page().runJavaScript(
                        "JSON.stringify({"
                        "zoom: map.getZoom(), "
                        "loadedTiles: document.querySelectorAll('.leaflet-tile-loaded').length"
                        "})",
                        lambda value: (result.update(js=value), loop.quit()),
                    )

                QTimer.singleShot(2000, check)

            view.loadFinished.connect(on_load_finished)
            view.setHtml(document, QUrl.fromLocalFile(str(tmp) + "/"))
            QTimer.singleShot(9000, loop.quit)
            loop.exec()

        self.assertTrue(result.get("load_finished_ok"))
        # The fitBounds computation itself is Leaflet's own algorithm,
        # not this app's code -- assert the *symptom* that matters
        # (tiles rendered) rather than pinning an exact zoom number that
        # could shift with viewport size or a future Leaflet upgrade.
        self.assertNotIn('"loadedTiles":0', result.get("js", ""))


if __name__ == "__main__":
    unittest.main()
