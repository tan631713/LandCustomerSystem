"""Smoke tests for the console's hand-drawn widgets (server_console/ui_*.py).

They need a Tk display; on a machine without one the whole module is skipped.
"""

from __future__ import annotations

import tkinter as tk
import unittest
from collections import namedtuple

try:  # the console is Windows-only; other platforms have no display in CI
    _ROOT = tk.Tk()
    _ROOT.withdraw()
except tk.TclError:  # pragma: no cover - headless machine
    _ROOT = None

if _ROOT is not None:
    from server_console import ui_theme
    from server_console.ui_panels import ConnectionPanel, StatusBar, StepsPanel, SystemPanel, TabBar
    from server_console.ui_theme import BROWN, GREEN, RED, TEXT, blend, px
    from server_console.ui_widgets import (
        Box, CanvasButton, Dropdown, Label, RoundedEntry, ellipsize, fit_text, rounded_image,
    )

Step = namedtuple("Step", "n name status reason")


class _Event:
    def __init__(self, x, y):
        self.x, self.y = x, y


@unittest.skipIf(_ROOT is None, "no Tk display available")
class ThemeHelperTests(unittest.TestCase):
    def setUp(self):
        ui_theme.init_scale(_ROOT)

    def test_px_never_collapses_a_positive_size(self):
        self.assertEqual(ui_theme.px(0), 0)
        self.assertGreaterEqual(ui_theme.px(0.2), 1)
        self.assertGreaterEqual(ui_theme.px(10), 10)

    def test_disabled_colours_are_the_45_percent_mix(self):
        self.assertEqual(blend("#000000", "#FFFFFF", 0.45), "#8C8C8C")
        self.assertEqual(blend("#FFFFFF", "#FFFFFF", 0.45), "#FFFFFF")

    def test_ellipsize_keeps_short_text_and_marks_cut_text(self):
        self.assertEqual(ellipsize("abc", 10), "abc")
        cut = ellipsize("0123456789", 5)
        self.assertEqual(len(cut), 5)
        self.assertTrue(cut.endswith("…"))

    def test_fit_text_shortens_to_the_available_pixels(self):
        font = ui_theme.scaled_font(14)
        text = "2026-07-17 15:43 · 共 2 份"
        limit = font.measure(text) // 2
        fitted = fit_text(font, text, limit)
        self.assertTrue(fitted.endswith("…"))
        self.assertLessEqual(font.measure(fitted), limit)
        self.assertEqual(fit_text(font, "abc", 100000), "abc")
        self.assertEqual(fit_text(font, "abc", 1), "…")

    def test_rounded_image_has_the_requested_size_and_transparent_corner_colour(self):
        picture = rounded_image(40, 30, 8, "#FF0000", "#00FF00", 2, "#0000FF")
        self.assertEqual(picture.size, (40, 30))
        self.assertEqual(picture.getpixel((0, 0)), (0, 0, 255))  # corner shows the backdrop
        self.assertEqual(picture.getpixel((20, 15)), (255, 0, 0))  # centre is the fill


@unittest.skipIf(_ROOT is None, "no Tk display available")
class WidgetTests(unittest.TestCase):
    def setUp(self):
        ui_theme.init_scale(_ROOT)
        self.holder = Box(_ROOT, bg="#FFFFFF")
        self.holder.pack()

    def tearDown(self):
        self.holder.destroy()

    def test_label_maps_text_color_and_scales_geometry_padding(self):
        label = Label(self.holder, "hello", 14, color=TEXT)
        label.configure(text_color=RED)
        self.assertEqual(str(label.cget("fg")), RED)
        label.pack(padx=(2, 4), pady=3)
        info = label.pack_info()
        self.assertEqual(int(info["pady"]), px(3))
        self.assertEqual(tuple(int(v) for v in info["padx"]) if isinstance(info["padx"], tuple) else int(info["padx"]),
                         (px(2), px(4)))

    def test_button_click_runs_command_only_while_enabled(self):
        calls = []
        button = CanvasButton(self.holder, "go", lambda: calls.append(1), "green", "play")
        button.pack()
        _ROOT.update()
        inside = _Event(0, 0)  # the window is never mapped in this test, so it is 1 px wide
        button._on_release(inside)
        self.assertEqual(calls, [1])
        button.set_enabled(False)
        button._on_release(inside)
        self.assertEqual(calls, [1])
        button.set_enabled(True)
        button._on_release(_Event(-10, 5))  # released outside the button: no click
        self.assertEqual(calls, [1])

    def test_button_widens_for_the_longest_alternative_label(self):
        plain = CanvasButton(self.holder, "啟動", None, "green")
        wide = CanvasButton(self.holder, "啟動", None, "green", texts=("重新啟動",))
        self.assertGreater(int(wide.cget("width")), int(plain.cget("width")))

    def test_entry_shows_placeholder_only_while_empty(self):
        variable = tk.StringVar()
        entry = RoundedEntry(self.holder, variable, placeholder="例如 chen.office")
        entry.pack(fill="x")
        _ROOT.update()
        self.assertEqual(entry.itemcget(entry._placeholder, "state"), "normal")
        variable.set("x")
        self.assertEqual(entry.itemcget(entry._placeholder, "state"), "hidden")

    def test_secret_entry_masks_input(self):
        entry = RoundedEntry(self.holder, tk.StringVar(), secret=True)
        self.assertEqual(str(entry.entry.cget("show")), "•")

    def test_dropdown_keeps_selection_when_values_change(self):
        picker = Dropdown(self.holder, ["a", "b"])
        picker.pack(fill="x")
        picker.set("b")
        picker.configure_values(["a", "b", "c"])
        self.assertEqual(picker.get(), "b")


@unittest.skipIf(_ROOT is None, "no Tk display available")
class PanelTests(unittest.TestCase):
    def setUp(self):
        ui_theme.init_scale(_ROOT)
        self.window = tk.Toplevel(_ROOT)
        self.window.geometry("%dx%d" % (px(900), px(700)))
        self.window.grid_columnconfigure(0, weight=1)

    def tearDown(self):
        self.window.destroy()

    def test_steps_show_a_reason_only_for_failed_or_skipped_rows(self):
        panel = StepsPanel(self.window, 3)
        panel.grid(row=0, column=0, sticky="ew")
        self.window.update()
        panel.set_rows([Step(1, "a", "done", ""), Step(2, "b", "failed", "缺少 PostgreSQL"), Step(3, "c", "pending", "x")])
        self.window.update()
        states = [panel.itemcget(row["reason"], "state") for row in panel._rows]
        self.assertEqual(states, ["hidden", "normal", "hidden"])
        tall = int(float(panel.cget("height")))
        panel.set_rows([Step(1, "a", "done", ""), Step(2, "b", "done", ""), Step(3, "c", "done", "")])
        self.window.update()
        self.assertLess(int(float(panel.cget("height"))), tall)

    def test_steps_label_each_state_in_traditional_chinese(self):
        panel = StepsPanel(self.window, 5)
        panel.grid(row=0, column=0, sticky="ew")
        panel.set_rows([Step(1, "a", "done", ""), Step(2, "b", "running", ""), Step(3, "c", "failed", "r"),
                        Step(4, "d", "skipped", "r"), Step(5, "e", "pending", "")])
        labels = [panel.itemcget(row["status"], "text") for row in panel._rows]
        self.assertEqual(labels, ["完成", "進行中", "失敗", "略過", "未執行"])

    def test_connection_values_truncate_with_an_ellipsis_and_enable_copy(self):
        panel = ConnectionPanel(self.window, lambda key: None)
        panel.grid(row=0, column=0, sticky="ew")
        self.window.update()
        long_value = "4BD97AB29BE2A50140021BB95E562D924223C769870237597E0A1212FCF84F76" * 3
        panel.set_values({"api_url": "https://100.107.93.232:8732/mobile/", "certificate_sha256": long_value})
        self.window.update()
        shown = panel.itemcget(panel._value_items["certificate_sha256"], "text")
        self.assertTrue(shown.endswith("…"))
        self.assertLess(len(shown), len(long_value))
        self.assertEqual(panel.itemcget(panel._value_items["netbird_ip"], "text"), "—")
        self.assertTrue(panel.copy_buttons["api_url"]._enabled)
        self.assertFalse(panel.copy_buttons["netbird_ip"]._enabled)

    def test_system_values_are_cut_to_their_column_instead_of_overlapping(self):
        panel = SystemPanel(self.window)
        panel.grid(row=0, column=0, sticky="ew")
        panel.set_value("backup", "2026-07-17 15:43 · 共 200 份 " * 3)
        self.window.update()
        shown = panel.itemcget(panel._values["backup"], "text")
        self.assertTrue(shown.endswith("…"))
        right_edge = panel.bbox(panel._values["backup"])[2]
        self.assertLessEqual(right_edge, panel.winfo_width())

    def test_system_values_can_be_coloured(self):
        panel = SystemPanel(self.window)
        panel.grid(row=0, column=0, sticky="ew")
        panel.set_value("accounts", "0（需要建立）", BROWN)
        self.assertEqual(panel.itemcget(panel._values["accounts"], "fill"), BROWN)
        self.assertEqual(panel.itemcget(panel._values["records"], "text"), "—")

    def test_status_bar_shows_shortcuts_only_without_accounts_and_pid_only_when_running(self):
        bar = StatusBar(self.window, lambda: None, lambda: None)
        bar.grid(row=0, column=0, sticky="ew")
        self.window.update()
        bar.set_state("no_accounts", "運作中 · 資料庫尚無帳號", "請建立第一個管理員", "PID 1 · :8732")
        self.assertEqual(bar.itemcget(bar._bootstrap_item, "state"), "normal")
        self.assertEqual(bar.itemcget(bar._pid, "text"), "")
        bar.set_state("running", "運作中", "ok", "PID 1 · :8732")
        self.assertEqual(bar.itemcget(bar._bootstrap_item, "state"), "hidden")
        self.assertEqual(bar.itemcget(bar._pid, "text"), "PID 1 · :8732")
        bar.set_state("error", "錯誤：缺少必要軟體", "x" * 400, "")
        self.window.update()
        # a long reason wraps onto more lines, making the bar taller instead of overflowing
        self.assertGreater(int(float(bar.cget("height"))), px(86))

    def test_tab_bar_maps_clicks_to_tabs_and_underlines_the_active_one(self):
        chosen = []
        bar = TabBar(self.window, (("log", "日誌"), ("management", "管理")), chosen.append)
        bar.grid(row=0, column=0, sticky="ew")
        self.window.update()
        bar.set_active("management")
        self.assertEqual(bar.itemcget(bar._underline, "state"), "normal")
        left, right = bar._cells["management"]
        bar._click(_Event((left + right) // 2, px(10)))
        self.assertEqual(chosen, ["management"])
        bar._click(_Event(px(400), px(10)))  # empty area: nothing selected
        self.assertEqual(chosen, ["management"])


if __name__ == "__main__":
    unittest.main()
