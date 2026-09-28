import unittest

from server_console.state import compute_display_state
from server_console.migration_client import _extract_json


class ComputeDisplayStateTests(unittest.TestCase):
    def test_port_open_means_running_even_without_a_tracked_process(self):
        state = compute_display_state(
            {}, process_alive=False, port_open=True, is_stopping=False,
            startup_elapsed_seconds=None,
        )
        self.assertEqual(state.status, "running")

    def test_error_status_in_diagnostics_wins_over_alive_process(self):
        state = compute_display_state(
            {"status": "error", "message": "缺少必要軟體：NetBird 私人 VPN。"},
            process_alive=True, port_open=False, is_stopping=False,
            startup_elapsed_seconds=5,
        )
        self.assertEqual(state.status, "error")
        self.assertIn("NetBird", state.reason)

    def test_starting_while_process_alive_and_port_not_yet_open(self):
        state = compute_display_state(
            {"status": "starting", "stage": "netbird", "message": "[2/7] 檢查 NetBird 私人 VPN..."},
            process_alive=True, port_open=False, is_stopping=False,
            startup_elapsed_seconds=10,
        )
        self.assertEqual(state.status, "starting")
        self.assertEqual(state.stage, "netbird")

    def test_startup_timeout_becomes_error_without_killing_anything(self):
        state = compute_display_state(
            {"status": "starting", "stage": "https"},
            process_alive=True, port_open=False, is_stopping=False,
            startup_elapsed_seconds=121,
        )
        self.assertEqual(state.status, "error")
        self.assertIn("2 分鐘", state.reason)

    def test_not_started_when_nothing_is_alive_and_no_diagnostics_yet(self):
        state = compute_display_state(
            {}, process_alive=False, port_open=False, is_stopping=False,
            startup_elapsed_seconds=None,
        )
        self.assertEqual(state.status, "not_started")

    def test_stopping_overrides_everything_else(self):
        state = compute_display_state(
            {"status": "running"}, process_alive=True, port_open=True,
            is_stopping=True, startup_elapsed_seconds=None,
        )
        self.assertEqual(state.status, "stopping")

    def test_unexpected_exit_while_diagnostics_still_says_running(self):
        state = compute_display_state(
            {"status": "running", "stage": "server"},
            process_alive=False, port_open=False, is_stopping=False,
            startup_elapsed_seconds=None,
        )
        self.assertEqual(state.status, "error")


class ExtractJsonTests(unittest.TestCase):
    def test_finds_json_after_leading_prompt_text(self):
        text = "單機版登入帳號（直接按 Enter 使用 User）：\n{\n  \"status\": \"ok\"\n}\n"
        self.assertEqual(_extract_json(text), {"status": "ok"})

    def test_returns_none_when_no_json_present(self):
        self.assertIsNone(_extract_json("純文字，沒有 JSON"))


if __name__ == "__main__":
    unittest.main()
