"""Compatibility launcher for the desktop UI.

Run this from the configured conda environment:

    python gui.py           # 原生客户端(macOS: SwiftUI,Windows: WinUI 3)
    python gui.py --tauri   # 旧版 Tauri + React 界面(已停止发布,仅供开发对照)

The verified backend remains Python. This launcher tells the desktop shell which
Python executable to use for gui_backend.py / ng_service.py, monitor.py, and bootstrap.py.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def backend_env() -> dict[str, str]:
    env = os.environ.copy()
    env["SJTU_MONITOR_PYTHON"] = sys.executable
    env["SJTU_MONITOR_ROOT"] = str(ROOT)
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUNBUFFERED", "1")
    return env


def run_tauri() -> int:
    npm = shutil.which("npm")
    if not npm:
        print("未找到 npm。请先安装 Node.js，然后运行 npm install。", file=sys.stderr)
        return 1

    node_modules = ROOT / "node_modules"
    if not node_modules.exists():
        print("未找到 node_modules。请先运行 npm install。", file=sys.stderr)
        return 1

    cmd = [npm, "run", "tauri", "dev"]
    print("$ " + " ".join(cmd))
    try:
        return subprocess.call(cmd, cwd=ROOT, env=backend_env())
    except KeyboardInterrupt:
        return 130


def run_ng() -> int:
    env = backend_env()
    if sys.platform == "darwin":
        script = ROOT / "ng" / "macos" / "build-app.sh"
        print(f"$ {script} debug")
        if subprocess.call([str(script), "debug"], cwd=ROOT) != 0:
            return 1
        # 直接执行 .app 内的可执行文件(而不是 `open`),环境变量才能传给后端定位;
        # 仍在 .app 里运行,通知等依赖 bundle identifier 的系统能力可用。
        binary = ROOT / "ng" / "macos" / "build" / "交我选.app" / "Contents" / "MacOS" / "JiaoWoXuan"
        cmd = [str(binary)]
    elif sys.platform == "win32":
        dotnet = shutil.which("dotnet")
        if not dotnet:
            print("未找到 dotnet。请先安装 .NET SDK 10。", file=sys.stderr)
            return 1
        project = ROOT / "ng" / "windows" / "JiaoWoXuan" / "JiaoWoXuan.csproj"
        # WinUI 3 需要具体平台;按本机架构选 ARM64 或 x64。
        arm = platform.machine().lower() in ("arm64", "aarch64")
        cmd = [
            dotnet, "run", "--project", str(project),
            f"-p:Platform={'ARM64' if arm else 'x64'}",
            "-r", "win-arm64" if arm else "win-x64",
        ]
    else:
        print("ng 原生客户端目前只支持 macOS 与 Windows。", file=sys.stderr)
        return 1
    print("$ " + " ".join(cmd))
    try:
        return subprocess.call(cmd, cwd=ROOT, env=env)
    except KeyboardInterrupt:
        return 130


def main() -> int:
    if "--tauri" in sys.argv[1:]:
        return run_tauri()
    return run_ng()


if __name__ == "__main__":
    raise SystemExit(main())
