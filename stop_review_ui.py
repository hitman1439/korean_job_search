#!/usr/bin/env python3
"""Stop a running review_ui.py server by the port it listens on."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys


IS_WINDOWS = sys.platform == "win32"


def run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    return result.stdout


def listening_pids(port: int) -> set[int]:
    if not IS_WINDOWS:
        return {int(pid) for pid in run(["lsof", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"]).split()}

    pids: set[int] = set()
    for line in run(["netstat", "-ano", "-p", "TCP"]).splitlines():
        parts = line.split()
        # Proto  Local Address  Foreign Address  State  PID
        if len(parts) == 5 and parts[3] == "LISTENING" and parts[1].endswith(f":{port}"):
            pids.add(int(parts[4]))
    return pids


def command_line(pid: int) -> str:
    if not IS_WINDOWS:
        return run(["ps", "-o", "args=", "-p", str(pid)]).strip()
    query = f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine"
    return run(["powershell", "-NoProfile", "-Command", query]).strip()


def kill(pid: int) -> None:
    if IS_WINDOWS:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, check=True)
    else:
        os.kill(pid, signal.SIGTERM)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stop the local job review UI.")
    parser.add_argument("--port", type=int, default=8765, help="Port the review UI listens on")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    # Only touch review_ui.py processes: `tailscale serve --https=8765` makes
    # tailscaled listen on the same port (on the tailnet IP) and must survive.
    targets = {pid: cmd for pid in listening_pids(args.port) if "review_ui.py" in (cmd := command_line(pid))}
    if not targets:
        print(f"포트 {args.port}에서 실행 중인 review_ui.py가 없습니다.")
        return 0

    for pid, cmdline in sorted(targets.items()):
        kill(pid)
        print(f"종료했습니다: PID {pid} ({cmdline})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
