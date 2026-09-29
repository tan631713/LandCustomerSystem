import datetime
import unittest

from server_console.state import (
    StepView,
    compute_display_state,
    step_log_line,
    steps_from_diagnostics,
)


def make_steps(*statuses, reasons=None):
    names = ("檢查必要軟體", "檢查 NetBird 連線", "啟動 PostgreSQL", "檢查資料庫",
             "遷移與帳號恢復", "自動備份", "啟動 HTTPS 伺服器")
    keys = ("prerequisites", "netbird", "postgresql", "database",
            "migration_recovery", "backup", "server")
    reasons = reasons or {}
    padded = list(statuses) + ["pending"] * (7 - len(statuses))
    return [
        {"n": i + 1, "key": keys[i], "name": names[i], "status": padded[i],
         "reason": reasons.get(i + 1, "")}
        for i in range(7)
    ]


def state(diagnostics, *, alive=False, port=False, stopping=False, elapsed=None, started_at=None):
    return compute_display_state(
        diagnostics, process_alive=alive, port_open=port, is_stopping=stopping,
        startup_elapsed_seconds=elapsed, started_at=started_at,
    )


class RunningStates(unittest.TestCase):
    def test_port_open_means_running_and_finishes_every_step(self):
        result = state({"steps": make_steps("done", "done", "done", "done", "done", "skipped", "running")},
                       port=True)
        self.assertEqual(result.status, "running")
        self.assertEqual(result.title, "運作中")
        self.assertIn("縮到系統匣", result.reason)
        self.assertEqual([s.status for s in result.steps],
                         ["done"] * 5 + ["skipped", "done"])

    def test_zero_accounts_is_the_warning_variant_with_next_steps(self):
        result = state({"account_count": 0}, port=True)
        self.assertEqual(result.status, "no_accounts")
        self.assertEqual(result.title, "運作中 · 資料庫尚無帳號")
        self.assertIn("建立第一個管理員", result.reason)
        self.assertIn("匯入遷移包", result.reason)

    def test_running_without_a_tracked_process_is_still_running(self):
        self.assertEqual(state({}, port=True).status, "running")


class StartingStates(unittest.TestCase):
    def test_current_step_number_and_name_come_from_the_ps1_steps(self):
        result = state({"status": "starting", "steps": make_steps("done", "done", "running")},
                       alive=True, elapsed=8)
        self.assertEqual(result.status, "starting")
        self.assertEqual(result.title, "啟動中 · 第 3/7 步")
        self.assertEqual(result.reason, "啟動 PostgreSQL…")
        self.assertEqual(result.current_step, 3)

    def test_diagnostics_written_before_this_run_are_ignored(self):
        began = datetime.datetime.now().astimezone()
        old = (began - datetime.timedelta(hours=3)).isoformat()
        result = state({"checked_at": old, "status": "running",
                        "steps": make_steps(*["done"] * 7)},
                       alive=True, elapsed=1, started_at=began)
        self.assertEqual(result.status, "starting")
        self.assertEqual(result.title, "啟動中 · 第 1/7 步")
        self.assertTrue(all(s.status == "pending" for s in result.steps))

    def test_timeout_marks_the_stuck_step_failed_without_killing_anything(self):
        result = state({"status": "starting", "steps": make_steps("done", "running")},
                       alive=True, elapsed=121)
        self.assertEqual(result.status, "error")
        self.assertEqual(result.title, "錯誤：啟動逾時")
        self.assertEqual(result.steps[1].status, "failed")


class ErrorStates(unittest.TestCase):
    def test_missing_software_without_winget(self):
        result = state({"status": "error", "stage": "prerequisites", "software_check": "missing",
                        "missing_software": ["PostgreSQL Server 18"], "winget_available": False,
                        "message": "缺少必要軟體...",
                        "steps": make_steps(*["failed"])})
        self.assertEqual(result.title, "錯誤：缺少必要軟體")
        self.assertEqual(
            result.reason,
            "缺少 PostgreSQL Server 18，且找不到 winget 無法自動安裝。請從官網手動安裝後按「啟動」。",
        )
        self.assertEqual(result.steps[0].status, "failed")
        self.assertTrue(all(s.status == "pending" for s in result.steps[1:]))

    def test_netbird_not_logged_in(self):
        result = state({"status": "error", "stage": "netbird",
                        "message": "NetBird 尚未登入或連線；請完成瀏覽器登入後再執行一次。"})
        self.assertEqual(result.title, "錯誤：NetBird 未連線")
        self.assertIn("請開啟 NetBird 並登入", result.reason)

    def test_port_occupied(self):
        result = state({"status": "error", "message": "連接埠 8732 已被其他程式占用（PID 4321），請關閉舊伺服器視窗後再試。"})
        self.assertEqual(result.title, "錯誤：8732 已被占用")
        self.assertIn("PID 4321", result.reason)

    def test_generic_message_gets_a_next_step(self):
        result = state({"status": "error", "message": "HTTPS 憑證建立失敗。"})
        self.assertEqual(result.title, "錯誤：啟動失敗")
        self.assertTrue(result.reason.startswith("HTTPS 憑證建立失敗。"))
        self.assertIn("按「啟動」", result.reason)

    def test_unexpected_exit_while_diagnostics_still_say_running(self):
        result = state({"status": "running", "steps": make_steps(*["done"] * 6 + ["running"])})
        self.assertEqual(result.title, "錯誤：伺服器已停止回應")
        self.assertEqual(result.steps[6].status, "failed")
        self.assertEqual(result.steps[5].status, "done")


class IdleStates(unittest.TestCase):
    def test_not_started_shows_every_step_pending_even_with_stale_diagnostics(self):
        result = state({"status": "stopped", "steps": make_steps(*["done"] * 7)})
        self.assertEqual(result.status, "not_started")
        self.assertEqual(result.title, "未啟動")
        self.assertEqual(result.reason, "伺服器已停止，手機與公司筆電目前無法連線。")
        self.assertTrue(all(s.status == "pending" for s in result.steps))

    def test_stopping_overrides_everything(self):
        result = state({"status": "running"}, alive=True, port=True, stopping=True)
        self.assertEqual(result.status, "stopping")
        self.assertEqual(result.title, "停止中")


class StepsAndLog(unittest.TestCase):
    def test_older_diagnostics_without_steps_fall_back_to_the_stage(self):
        steps = steps_from_diagnostics({"stage": "database"})
        self.assertEqual([s.status for s in steps],
                         ["done", "done", "done", "running", "pending", "pending", "pending"])

    def test_log_lines_mirror_the_mock(self):
        done = StepView(1, "prerequisites", "檢查必要軟體", "done")
        with_reason = StepView(2, "netbird", "檢查 NetBird 連線", "done", "NetBird 私人 VPN 已就緒 100.1.2.3")
        skipped = StepView(6, "backup", "自動備份", "skipped", "24 小時內已有備份，略過自動備份")
        failed = StepView(3, "postgresql", "啟動 PostgreSQL", "failed", "找不到服務")
        running_last = StepView(7, "server", "啟動 HTTPS 伺服器", "running")
        running_mid = StepView(3, "postgresql", "啟動 PostgreSQL", "running")
        self.assertEqual(step_log_line(done), ("info", "[1/7] 檢查必要軟體… 完成"))
        self.assertEqual(step_log_line(with_reason), ("info", "[2/7] NetBird 私人 VPN 已就緒 100.1.2.3"))
        self.assertEqual(step_log_line(skipped), ("info", "[6/7] 24 小時內已有備份，略過自動備份"))
        self.assertEqual(step_log_line(failed), ("error", "[3/7] 啟動 PostgreSQL失敗：找不到服務"))
        self.assertEqual(step_log_line(running_last), ("info", "[7/7] 啟動 HTTPS 伺服器…"))
        self.assertIsNone(step_log_line(running_mid))


if __name__ == "__main__":
    unittest.main()
