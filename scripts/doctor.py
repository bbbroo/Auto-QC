from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = REPO_ROOT / "frontend"
DATA_DIR = REPO_ROOT / "data"


def main() -> int:
    parser = argparse.ArgumentParser(description="Check whether the local AutoQC development environment is ready.")
    parser.add_argument("--full", action="store_true", help="Also run pytest, frontend typecheck, and frontend build.")
    args = parser.parse_args()

    checks: list[tuple[str, bool, str]] = []
    checks.append(("Python version", sys.version_info >= (3, 11), sys.version.split()[0]))
    checks.append(("Repository root", (REPO_ROOT / "backend" / "app" / "main.py").exists(), str(REPO_ROOT)))
    checks.append(("Frontend package", (FRONTEND_DIR / "package.json").exists(), str(FRONTEND_DIR / "package.json")))
    checks.append(("Node executable", shutil.which("node") is not None, shutil.which("node") or "not found"))
    checks.append(("NPM executable", shutil.which("npm") is not None, shutil.which("npm") or "not found"))
    checks.append(("Frontend dependencies", (FRONTEND_DIR / "node_modules").exists(), "run npm install in frontend if missing"))
    checks.append(("Playwright config", (FRONTEND_DIR / "playwright.config.ts").exists(), "browser tests configured"))
    checks.append(("Data directory writable", check_writable(DATA_DIR), str(DATA_DIR)))
    checks.append(("Port 8000 available", port_available(8000), "backend default"))
    checks.append(("Port 5173 available", port_available(5173), "frontend default"))

    if args.full:
        npm_executable = shutil.which("npm") or "npm"
        checks.append(run_command("Backend pytest", [sys.executable, "-m", "pytest"], REPO_ROOT))
        checks.append(run_command("Frontend typecheck", [npm_executable, "run", "typecheck"], FRONTEND_DIR))
        checks.append(run_command("Frontend build", [npm_executable, "run", "build"], FRONTEND_DIR))

    failed = False
    print("AutoQC Doctor")
    print("=============")
    for name, ok, detail in checks:
        marker = "PASS" if ok else "FAIL"
        print(f"[{marker}] {name}: {detail}")
        failed = failed or not ok

    if failed:
        print("\nEnvironment is not fully ready. Fix FAIL items before company-use validation.")
        return 1

    print("\nEnvironment looks ready for local AutoQC use.")
    return 0


def check_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".doctor-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) != 0


def run_command(name: str, command: list[str], cwd: Path) -> tuple[str, bool, str]:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=120,
            check=False,
            env={**os.environ, "PYTHONUTF8": "1"},
        )
    except Exception as exc:
        return name, False, str(exc)

    last_lines = " ".join(completed.stdout.strip().splitlines()[-3:]) if completed.stdout else "no output"
    return name, completed.returncode == 0, last_lines[:240]


if __name__ == "__main__":
    raise SystemExit(main())
