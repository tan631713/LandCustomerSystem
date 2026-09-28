"""Pure state-determination logic, kept separate from Tk so it is unit
testable without a display. See the inventory report: [n/M] text in
home_server_runtime.ps1's own output is not a reliable progress source
(inconsistent denominator, a conditional step), so status is judged only
from the diagnostics file's `status`/`stage` plus the two live checks the
spec asks for: process alive and 127.0.0.1:8732 reachable.
"""

from __future__ import annotations

from dataclasses import dataclass

STARTUP_TIMEOUT_SECONDS = 120
STOP_WAIT_SECONDS = 15
AUTO_RESTART_WINDOW_SECONDS = 10 * 60
AUTO_RESTART_MAX_ATTEMPTS = 3


@dataclass
class DisplayState:
    status: str  # not_started | starting | running | error | stopping
    reason: str
    stage: str = ""


def compute_display_state(
    diagnostics: dict,
    *,
    process_alive: bool,
    port_open: bool,
    is_stopping: bool,
    startup_elapsed_seconds: float | None,
) -> DisplayState:
    if is_stopping:
        return DisplayState("stopping", "正在停止伺服器...")

    if port_open:
        return DisplayState("running", "運作中")

    diagnostics_status = str(diagnostics.get("status") or "")
    message = str(diagnostics.get("message") or "")
    stage = str(diagnostics.get("stage") or "")

    if diagnostics_status == "error":
        return DisplayState("error", message or "發生錯誤，請查看日誌。", stage)

    if process_alive:
        if startup_elapsed_seconds is not None and startup_elapsed_seconds > STARTUP_TIMEOUT_SECONDS:
            return DisplayState("error", "啟動超過 2 分鐘未完成，請查看日誌分頁最後的錯誤。", stage)
        return DisplayState("starting", message or "啟動中...", stage)

    if diagnostics_status in ("running", "already_running") and not port_open:
        # 診斷檔說運作中，但連不上 8732 且行程也不在——伺服器已經意外中止。
        return DisplayState("error", "伺服器已停止回應，連不上連接埠 8732。", stage)

    return DisplayState("not_started", "未啟動")
