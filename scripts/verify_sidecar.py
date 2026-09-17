"""发布前自检冻结后端:selfcheck + 以匿名管道启动 ng_service(与原生客户端相同的方式)。

    python scripts/verify_sidecar.py <sidecar 可执行文件>
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile


def main() -> int:
    # CI 的 Windows 控制台默认 cp1252,打印中文会失败
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    exe = sys.argv[1]
    check = subprocess.run([exe, "selfcheck"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
    text = check.stdout.decode("utf-8", "replace")
    print(text, check.stderr.decode("utf-8", "replace"))
    if check.returncode != 0 or "中文编码验证：交我选" not in text:
        print("selfcheck 失败")
        return 1

    with tempfile.TemporaryDirectory() as data_dir:
        env = {**os.environ, "SJTU_MONITOR_DATA_DIR": data_dir}
        requests = b"".join(
            json.dumps(r).encode() + b"\n"
            for r in [
                {"id": 1, "method": "hello", "params": {}},
                {"id": 2, "method": "demo.enter", "params": {}},
                {"id": 3, "method": "snapshot", "params": {}},
            ]
        )
        run = subprocess.run([exe, "ng_service.py"], input=requests, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, env=env, timeout=300)
    print(run.stderr.decode("utf-8", "replace"))
    responses = {}
    for line in run.stdout.decode("utf-8").splitlines():
        message = json.loads(line)
        if "id" in message:
            responses[message["id"]] = message
    print({k: str(v)[:120] for k, v in responses.items()})
    ok = (
        run.returncode == 0
        and responses.get(1, {}).get("result", {}).get("protocol") == 1
        and responses.get(1, {}).get("result", {}).get("version")
        and responses.get(3, {}).get("result", {}).get("demo") is True
    )
    if not ok:
        print(f"ng_service 自检失败,退出码 {run.returncode}")
        return 1
    print("sidecar ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
