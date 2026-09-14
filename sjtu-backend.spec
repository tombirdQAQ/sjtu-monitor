# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包规格:把 Python 后端冻结成独立可执行文件 sjtu-backend。

onedir(而非 onefile):sidecar 会被 GUI 频繁调用(snapshot/poll/换课),
onefile 每次启动都要把 ddddocr 的 onnxruntime(~150MB 原生库)重新解压到临时目录,
延迟明显;onedir 无解压、启动快,再由 Tauri 以 resources 形式整目录打包。

ddddocr / onnxruntime 带 ONNX 模型与原生 .dll/.so,PyInstaller 默认扫不全,
用 collect_all 显式收集数据文件、二进制与隐藏导入。
"""
import glob
import os
import sys

from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []

_WINDOWS = sys.platform.startswith("win")

# conda 环境把 _ctypes 依赖的 libffi 等原生 DLL 放在 <prefix>/Library/bin,
# PyInstaller 默认扫不到,导致冻结产物 `import ctypes` 失败。存在该布局时补收进来。
# CI 用 python.org 的 Python 无此目录,这段自然成为空操作。
_conda_bin = os.path.join(sys.prefix, "Library", "bin")
if os.path.isdir(_conda_bin):
    for _dll in glob.glob(os.path.join(_conda_bin, "ffi*.dll")):
        binaries.append((_dll, "."))
for pkg in ("ddddocr", "onnxruntime"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

# 后端各模块通过脚本名动态分发/懒加载,显式列为隐藏导入以防被裁剪。
hiddenimports += [
    "bs4", "PIL", "dotenv",
    "apppaths", "config", "secure_store", "notifier",
    "login", "timetable", "swap", "zzxk", "course_plus",
    "gui_backend", "monitor", "bootstrap",
]

# win11toast 在 notifier.py 里是函数内懒加载,Windows 独立版要靠它弹桌面通知,
# 必须显式收集(collect_all 才能带上它的数据文件),否则打包后通知失效。
# 它依赖 winsdk,非 Windows 平台根本装不上(requirements.txt 已加平台标记),
# 因此只在 Windows 上收集;macOS 走 osascript、Linux 走 notify-send,都是外部命令,
# 不需要任何打包期处理。
if _WINDOWS:
    hiddenimports.append("win11toast")
    try:
        w_datas, w_binaries, w_hidden = collect_all("win11toast")
        datas += w_datas
        binaries += w_binaries
        hiddenimports += w_hidden
    except Exception:
        pass

a = Analysis(
    ["backend_entry.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="sjtu-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # Windows 用 console=False:避免每次调用 sidecar 都弹出黑色控制台窗口。
    # Tauri 通过管道捕获 stdout/stderr,windowed 子进程的 JSON 输出仍能正常读取。
    # macOS/Linux 没有这个问题(子进程不会凭空开终端窗口),用 console=True 走标准
    # 命令行 bootloader,避开 windowed 模式在非 .app 布局下的额外行为差异。
    console=not _WINDOWS,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="sjtu-backend",
)
