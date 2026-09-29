"""Dev/test only: reproduce one UI scenario on this machine and capture it.

usage: python run_scenario.py NAME
NAME: not_started | starting | running | no_accounts | error_software | error_netbird

Starts the real console (source, not the exe) with LCS_CONSOLE_RUNTIME_SCRIPT
pointing at dev_tools/fake_runtime.ps1, and (for the running scenarios) a
throw-away TLS listener on 127.0.0.1:8732. Nothing here touches the real server.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
PYTHON = sys.executable
SCREENS = ROOT / "docs" / "console_screens"
MOCK = Path(os.path.expanduser("~")) / "Desktop" / "伺服器控制台 主視窗@2x.png"

SCENARIOS = {
    "not_started": dict(fake=None, listener=False, wait=4),
    "starting": dict(fake="starting", listener=False, wait=8),
    "running": dict(fake="running", listener=True, wait=9),
    "no_accounts": dict(fake="no_accounts", listener=True, wait=9),
    "error_software": dict(fake="missing_software", listener=False, wait=8),
    "error_netbird": dict(fake="netbird", listener=False, wait=8),
}


def kill_tree(pid):
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)


def kill_existing_consoles():
    script = (
        "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*server_console.main*' "
        "-or $_.CommandLine -like '*fake_listener.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True)


def main(name):
    config = SCENARIOS[name]
    diagnostics = Path(os.environ["LOCALAPPDATA"]) / "LandCustomerSystem" / "home-server-diagnostics.json"
    kill_existing_consoles()
    time.sleep(1)
    if diagnostics.exists():
        diagnostics.unlink()  # a clean slate so stale data cannot leak into the capture
    environment = dict(os.environ)
    if config["fake"]:
        environment["LCS_CONSOLE_RUNTIME_SCRIPT"] = str(HERE / "fake_runtime.ps1")
        environment["LCS_FAKE_SCENARIO"] = config["fake"]
    arguments = [PYTHON, "-m", "server_console.main"] + (["--auto-start"] if config["fake"] else [])
    console = subprocess.Popen(arguments, cwd=ROOT, env=environment)
    listener = None
    try:
        if config["listener"]:
            # 等控制台真的啟動了假的執行腳本（診斷檔出現）才開監聽埠；太早開的話
            # 控制台會以為 8732 已被占用而不啟動。
            deadline = time.time() + 40
            while not diagnostics.exists() and time.time() < deadline:
                time.sleep(0.5)
            listener = subprocess.Popen([PYTHON, str(HERE / "fake_listener.py")], cwd=ROOT)
        time.sleep(config["wait"])
        SCREENS.mkdir(parents=True, exist_ok=True)
        output = SCREENS / f"{name}.png"
        subprocess.run([PYTHON, str(HERE / "capture_window.py"), str(output), "--mock", str(MOCK)], cwd=ROOT)
    finally:
        kill_tree(console.pid)
        if listener:
            kill_tree(listener.pid)
        kill_existing_consoles()


if __name__ == "__main__":
    main(sys.argv[1])
