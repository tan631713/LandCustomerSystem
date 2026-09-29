"""Pure state-determination logic, kept separate from Tk so it is unit
testable without a display.

Status is judged only from the diagnostics file plus the two live checks the
spec asks for: the ps1 process this console started is alive and
127.0.0.1:8732 accepts a connection. The 7 visual steps come from the
structured `steps` list home_server_runtime.ps1 now writes into the
diagnostics file (not from parsing its human-readable "[n/M]" text, whose
numbering is inconsistent); older diagnostics files without `steps` fall back
to the `stage` field.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field

STARTUP_TIMEOUT_SECONDS = 120
STOP_WAIT_SECONDS = 15
AUTO_RESTART_WINDOW_SECONDS = 10 * 60
AUTO_RESTART_MAX_ATTEMPTS = 3

STEP_KEYS = (
    "prerequisites", "netbird", "postgresql", "database",
    "migration_recovery", "backup", "server",
)
DEFAULT_STEP_NAMES = (
    "檢查必要軟體", "檢查 NetBird 連線", "啟動 PostgreSQL", "檢查資料庫",
    "遷移與帳號恢復", "自動備份", "啟動 HTTPS 伺服器",
)
STEP_COUNT = len(STEP_KEYS)

# Fallback for diagnostics files written by an older ps1 (no `steps`):
# real `stage` value -> index of the last visual step reached.
_REACHED_BY_STAGE = {
    "prerequisites": 0, "netbird": 1, "windows_services": 2,
    "pre_upgrade_backup": 3, "database": 3, "https": 5, "backup": 5, "server": 6,
}

RUNNING_REASON = "手機與公司筆電可透過 NetBird 連線。關閉視窗會縮到系統匣，伺服器不會停止。"
NO_ACCOUNTS_REASON = "目前沒有任何帳號可以登入。請建立第一個管理員，或匯入遷移包。"
NOT_STARTED_REASON = "伺服器已停止，手機與公司筆電目前無法連線。"


@dataclass
class StepView:
    n: int
    key: str
    name: str
    status: str  # pending | running | done | skipped | failed
    reason: str = ""


@dataclass
class DisplayState:
    status: str  # not_started | starting | running | no_accounts | error | stopping
    title: str
    reason: str
    stage: str = ""
    current_step: int | None = None
    steps: list[StepView] = field(default_factory=list)


def _parse_time(value) -> datetime.datetime | None:
    try:
        parsed = datetime.datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed


def is_stale(diagnostics: dict, started_at: datetime.datetime | None) -> bool:
    """True if the diagnostics file predates the run this console just began."""

    if not diagnostics or started_at is None:
        return False
    written = _parse_time(diagnostics.get("checked_at"))
    if written is None:
        return True
    return written < started_at


def summarize_error(diagnostics: dict) -> tuple[str, str]:
    """(short summary for the big title, full reason incl. next step)."""

    message = str(diagnostics.get("message") or "").strip()
    missing = [str(item) for item in (diagnostics.get("missing_software") or [])]
    stage = str(diagnostics.get("stage") or "")
    if missing and (stage == "prerequisites" or diagnostics.get("software_check") == "missing"):
        names = "、".join(missing)
        if not diagnostics.get("winget_available"):
            return "缺少必要軟體", f"缺少 {names}，且找不到 winget 無法自動安裝。請從官網手動安裝後按「啟動」。"
        return "缺少必要軟體", f"缺少 {names}。請先用「啟動家中伺服器.bat」完成一次安裝，或從官網手動安裝後按「啟動」。"
    if "NetBird" in message and ("尚未登入" in message or "連線" in message):
        return "NetBird 未連線", "NetBird 尚未登入或連線，手機與筆電無法連入。請開啟 NetBird 並登入後按「啟動」。"
    if "8732" in message and "占用" in message:
        return "8732 已被占用", f"{message}"
    if "非互動" in message or "非互動模式" in message:
        return "需要手動處理", message
    if stage == "windows_services" or "PostgreSQL" in message and "服務" in message:
        return "PostgreSQL 服務未就緒", f"{message} 請確認 PostgreSQL 服務後按「啟動」。".strip()
    if not message:
        return "啟動失敗", "沒有取得錯誤說明。請查看日誌分頁後按「啟動」重試。"
    return "啟動失敗", f"{message} 請查看日誌分頁，處理後按「啟動」。"


def _default_steps() -> list[StepView]:
    return [
        StepView(index + 1, key, DEFAULT_STEP_NAMES[index], "pending")
        for index, key in enumerate(STEP_KEYS)
    ]


def steps_from_diagnostics(diagnostics: dict) -> list[StepView]:
    """Normalise the ps1's `steps` (names come from the ps1, not hard-coded)."""

    raw = diagnostics.get("steps")
    if isinstance(raw, list) and raw:
        steps = []
        for index, item in enumerate(raw[:STEP_COUNT]):
            if not isinstance(item, dict):
                continue
            steps.append(
                StepView(
                    int(item.get("n") or index + 1),
                    str(item.get("key") or STEP_KEYS[min(index, STEP_COUNT - 1)]),
                    str(item.get("name") or DEFAULT_STEP_NAMES[min(index, STEP_COUNT - 1)]),
                    str(item.get("status") or "pending"),
                    str(item.get("reason") or ""),
                )
            )
        if steps:
            return steps
    steps = _default_steps()
    stage = str(diagnostics.get("stage") or "")
    if stage in _REACHED_BY_STAGE:
        reached = _REACHED_BY_STAGE[stage]
        for step in steps[:reached]:
            step.status = "done"
        steps[reached].status = "running"
    return steps


def _all_pending() -> list[StepView]:
    return _default_steps()


def _finish_pending_as_done(steps: list[StepView]) -> list[StepView]:
    for step in steps:
        if step.status in ("pending", "running"):
            step.status = "done"
    return steps


def _current_step(steps: list[StepView]) -> StepView:
    for step in steps:
        if step.status == "running":
            return step
    for step in steps:
        if step.status == "pending":
            return step
    return steps[-1]


def compute_display_state(
    diagnostics: dict,
    *,
    process_alive: bool,
    port_open: bool,
    is_stopping: bool,
    startup_elapsed_seconds: float | None,
    started_at: datetime.datetime | None = None,
) -> DisplayState:
    if is_stopping:
        return DisplayState("stopping", "停止中", "正在停止伺服器…", steps=_all_pending())

    if process_alive and is_stale(diagnostics, started_at):
        diagnostics = {}

    stage = str(diagnostics.get("stage") or "")

    if port_open:
        steps = _finish_pending_as_done(steps_from_diagnostics(diagnostics))
        if diagnostics.get("account_count") == 0:
            return DisplayState("no_accounts", "運作中 · 資料庫尚無帳號", NO_ACCOUNTS_REASON, stage, steps=steps)
        return DisplayState("running", "運作中", RUNNING_REASON, stage, steps=steps)

    diagnostics_status = str(diagnostics.get("status") or "")

    if diagnostics_status == "error":
        summary, reason = summarize_error(diagnostics)
        return DisplayState(
            "error", f"錯誤：{summary}", reason, stage, steps=steps_from_diagnostics(diagnostics)
        )

    if process_alive:
        steps = steps_from_diagnostics(diagnostics)
        if startup_elapsed_seconds is not None and startup_elapsed_seconds > STARTUP_TIMEOUT_SECONDS:
            current = _current_step(steps)
            current.status = "failed"
            current.reason = "啟動超過 2 分鐘未完成"
            return DisplayState(
                "error", "錯誤：啟動逾時", "啟動超過 2 分鐘未完成，請查看日誌分頁最後的錯誤。",
                stage, current.n, steps,
            )
        current = _current_step(steps)
        return DisplayState(
            "starting", f"啟動中 · 第 {current.n}/{STEP_COUNT} 步", f"{current.name}…",
            stage, current.n, steps,
        )

    if diagnostics_status in ("running", "already_running"):
        # 診斷檔說運作中，但連不上 8732 且行程也不在——伺服器已經意外中止。
        steps = _finish_pending_as_done(steps_from_diagnostics(diagnostics))
        steps[-1].status = "failed"
        steps[-1].reason = "伺服器已停止回應"
        return DisplayState(
            "error", "錯誤：伺服器已停止回應",
            "連不上連接埠 8732。請按「啟動」重新啟動，或到日誌分頁查看原因。",
            stage, steps=steps,
        )

    return DisplayState("not_started", "未啟動", NOT_STARTED_REASON, steps=_all_pending())


def step_log_line(step: StepView) -> tuple[str, str] | None:
    """(level, text) for a step that just changed status, mirroring the mock
    log ("[1/7] 檢查必要軟體… 完成" style). Nothing for pending."""

    prefix = f"[{step.n}/{STEP_COUNT}]"
    if step.status == "done":
        return "info", f"{prefix} {step.reason}" if step.reason else f"{prefix} {step.name}… 完成"
    if step.status == "skipped":
        return "info", f"{prefix} {step.reason or step.name + '… 略過'}"
    if step.status == "failed":
        return "error", f"{prefix} {step.name}失敗：{step.reason}" if step.reason else f"{prefix} {step.name}失敗"
    if step.status == "running" and step.n == STEP_COUNT:
        return "info", f"{prefix} {step.name}…"
    return None
